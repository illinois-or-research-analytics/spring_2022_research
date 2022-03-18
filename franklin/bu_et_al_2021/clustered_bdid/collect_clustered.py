# Utility Imports
import csv
from datetime import datetime
import sys
import time

import pandas as pd

from multiprocessing import Manager, Queue

import logging
import logging.handlers

# Custom class imports
from csv_writer import CsvWriter
from log_listener import LogListener
from worker import Worker


def main(max_cores: int = 8):

    # Format names of output files
    exec_time = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    start_time = time.time()
    csv_output = f"clustered_bdid_metrics-{exec_time}.csv"
    logfile_output = f"logfile_collect_clustered_{exec_time}.txt"

    # Spin up logging process
    log_queue = Queue()
    log_listener = LogListener(log_queue, logfile_output)
    log_listener.start()
    h = logging.handlers.QueueHandler(log_queue)
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    logger = logging.getLogger("Logger")

    print(
        f"Entered main function:\nWill generate output in {csv_output} and log to {logfile_output}"
    )
    logger.log(
        logging.INFO, f"Entered main function: Will generate output in {csv_output}"
    )
    print(f"Using {max_cores} CPU cores ({max_cores+2} including logger and csv_writer)...")
    logger.log(logging.INFO, f"Using {max_cores} CPU cores ({max_cores+2} including logger and csv_writer)...")

    print("Generating dataframe. This will take a minute...")
    logger.log(logging.INFO, "Generating dataframe. This will take a minute...")

    # Put edge list with each endpoint's cluster_id into a dataframe
    df_edges = pd.read_csv(
        "/srv/local/shared/external/for_eleanor/gc_exosome/citing_cited_network.integer.tsv",
        sep="\t",
        names=["citing_int_id", "cited_int_id"],
    )
    df_clusters = pd.read_csv(
        "/srv/local/shared/external/clusterings/exosome_1900_2010_sabpq/IKC+RG+Aug+kmp-parse/ikc-rg-aug_k_5_p_2.clustering",
        names=["citing_int_id", "citing_cluster_id"],
    )
    df_edges = df_edges.merge(df_clusters, on="citing_int_id", how="inner")
    df_clusters = pd.read_csv(
        "/srv/local/shared/external/clusterings/exosome_1900_2010_sabpq/IKC+RG+Aug+kmp-parse/ikc-rg-aug_k_5_p_2.clustering",
        names=["cited_int_id", "cited_cluster_id"],
    )
    df_edges = df_edges.merge(df_clusters, on="cited_int_id", how="inner")

    print(df_edges)
    logger.log(logging.INFO, f"\n{df_edges}")
    print("Done!")
    logger.log(logging.INFO, "Done!")
    print("Reading node list...")
    logger.log(logging.INFO, "Reading node list")

    # Read in the node list (currently using the sample)
    nodes_to_calc = Queue()
    manager = Manager()
    # Must use a manager-based queue to handle more than 64 child processes
    calculated_tuples = manager.Queue()
    # Full-scale: "/srv/local/shared/external/clusterings/exosome_1900_2010_sabpq/IKC+RG+Aug+kmp-parse/ikc-rg-aug_k_5_p_2.clustering"
    # Sample: "/srv/local/shared/external/dbid/franklins_sample.csv"
    with open(
        "/srv/local/shared/external/clusterings/exosome_1900_2010_sabpq/IKC+RG+Aug+kmp-parse/ikc-rg-aug_k_5_p_2.clustering",
        "r",
    ) as file:
        reader = csv.DictReader(file, fieldnames=["V1", "V2"])
        # reader = csv.DictReader(file)
        for row in reader:
            nodes_to_calc.put((int(row["V1"]), int(row["V2"])))

    nodes_read = nodes_to_calc.qsize()
    nodes_to_calc.put(None)
    print(f"Done! {nodes_read} nodes read.")
    logger.log(logging.INFO, f"Done! {nodes_read} nodes read.")
    print(
        f"Dispatching {max_cores} workers. This will take a while, so go outside and do something!"
    )
    logger.log(
        logging.INFO,
        f"Dispatching {max_cores} workers. This will take a while, so go outside and do something!",
    )

    # Prepare and dispatch worker processes
    workers = []
    for _ in range(max_cores):
        worker = Worker(
            nodes_to_calc, calculated_tuples, nodes_read, df_edges, log_queue
        )
        workers.append(worker)
        worker.start()

    # Start csv_writer
    csv_writer = CsvWriter(csv_output, calculated_tuples)
    csv_writer.start()

    # Wait for workers to finish and join
    for w in workers:
        w_pid = w.pid
        w.join()
        print(f"Closing process {w_pid}")
        logger.log(logging.INFO, f"Closing child process {w_pid}")

    # Tell the csv_writer process that the workers have finished
    calculated_tuples.put(None)
    csv_writer.join()
    print('Closing CsvWriter process')
    logger.log(logging.INFO, 'Closing CsvWriter process')

    run_time = time.time() - start_time
    print(f"Finished calculating BDID for {nodes_read} nodes in {run_time} seconds")
    logger.log(
        logging.INFO,
        f"Finished calculating BDID for {nodes_read} nodes in {run_time} seconds",
    )
    # Signal to the logger that we're done
    log_queue.put_nowait(None)
    log_queue.close()
    log_listener.join()


if __name__ == "__main__":
    if len(sys.argv) > 2:
        print("Too many arguments. See usage below:")
        print("Usage: collect_clustered.py [num_cores]")
        print("\tArguments:")
        print(
            "\t\tnum_cores: Optional. Maximum number of CPU cores to use. Defaults to 8."
        )
        exit(1)
    main(int(sys.argv[1]))

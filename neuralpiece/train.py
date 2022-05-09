#!/usr/bin/env python3

import argparse
import copy
import logging
import random
import multiprocessing

import torch
import torch.nn as nn

from neuralpiece.estimators import UniformEstimator, DotProdEstimator
from neuralpiece.model import Model
from neuralpiece.vocab import Vocab


logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument(
        "vocab", type=argparse.FileType("r"),
        help="Initial vocabulary.")
    parser.add_argument(
        "token_counts", type=argparse.FileType("r"),
        help="Tab-separated file with token counts.")
    parser.add_argument(
        "--num-threads", type=int, default=4,
        help="Number of threads.")
    parser.add_argument(
        "--batch-size", type=int, default=1024,
        help="Batch size for the neural model.")
    parser.add_argument(
        "--embedding-dim", type=int, default=300,
        help="Embedding dim in the neural model.")
    parser.add_argument(
        "--patience", type=int, default=10,
        help="Embedding dim in the neural model.")
    args = parser.parse_args()

    logging.info("Load vocabulary from '%s'.", args.vocab)
    vocab = Vocab([line.strip() for line in args.vocab])
    args.vocab.close()
    logging.info("Vocab size %d", vocab.size)

    logging.info("Load token counts from '%s'.", args.token_counts)
    token_counts = []
    for line in args.token_counts:
        token, count_str = line.strip().split()
        token_counts.append((token, int(count_str)))
    args.token_counts.close()
    split_size = len(token_counts) // args.num_threads + 1
    split_token_counts = [
        token_counts[i * split_size:(i + 1) * split_size]
        for i in range(args.num_threads)]
    logging.info(
        "Load %d tokens, %d per thread.", len(token_counts), split_size)

    logging.info("Initialize model.")
    estimator = UniformEstimator(vocab.size)
    model = Model(vocab, estimator)

    logging.info("Sample and count bigrams.")
    pool = multiprocessing.Pool(processes=args.num_threads)
    bigrams = []
    for thread_bigrams in pool.map(model.extract_bigrams, split_token_counts):
        bigrams.extend(thread_bigrams)

    random.shuffle(bigrams)

    logging.info("Start training neural model.")
    val_set = bigrams[:2000]
    val_prev_subwords, val_subwords = zip(*val_set)
    train_set = bigrams[2000:]
    neural_estimator = DotProdEstimator(vocab, args.embedding_dim)
    optimizer = torch.optim.Adam(neural_estimator.parameters(), lr=1e-4)
    stalled = 0
    best_loss = 1e9
    best_params = None

    @torch.no_grad()
    def validate():
        return -neural_estimator(val_subwords, val_prev_subwords).mean()

    for epoch in range(50):
        for i in range(0, len(train_set) // args.batch_size):
            prev_subwords, subwords = zip(
                *train_set[i * args.batch_size:(i + 1) * args.batch_size])
            loss = -neural_estimator(subwords, prev_subwords).mean()
            loss.backward()
            optimizer.step()

            if i % 10 == 9:
                val_loss = validate()
                logging.info(
                    "Epoch %d, batch %d, val loss: %.3g",
                    epoch + 1, i + 1, val_loss)
                if val_loss < best_loss:
                    best_loss = val_loss
                    best_params = copy.deepcopy(neural_estimator.state_dict())
                    stalled = 0
                else:
                    stalled += 1

            if stalled > args.patience:
                break
        if stalled > args.patience:
            break
    neural_estimator.load_state_dict(best_params)

    logging.info("Done.")


if __name__ == "__main__":
    main()

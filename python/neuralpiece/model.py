from typing import List, Callable, Any
import sys
import numpy as np
from scipy.special import logsumexp

from neuralpiece.vocab import Vocab


class Model:
    def __init__(
            self,
            vocab: Vocab,
            estimator: Callable[[Any], float],
            sample_temperature: float = 1.0,
            is_bert_wordpiece: bool = False) -> None:
        self.vocab = vocab
        self.estimator = estimator
        self.temperature = sample_temperature
        self.is_bert_wordpiece = is_bert_wordpiece

        self._cache = {}

    def segment(self, token: str, sample: bool = False) -> List[str]:
        assert token
        if token in self._cache:
            return self._cache[token]

        score_table = np.full([len(token), len(token)], -np.inf)
        prev_rows = np.full([len(token), len(token)], -1, dtype=np.int32)

        # on a given row there are all subwords beginning at index i
        for row in range(len(token)):
            max_column = min(len(token), row + self.vocab.max_subword_length)
            for col in range(row, max_column):

                subword = token[row:col + 1]
                if self.is_bert_wordpiece and row > 0:
                    subword = "##" + subword

                if subword not in self.vocab:
                    #if len(subword) == 1:
                    #    raise ValueError(f"character '{subword}' not in vocab")
                    continue

                if row == 0:
                    score_table[row, col] = self.estimator(subword, "###")
                    continue

                best_predecesor = (-np.inf, -1)
                predecesor_scores = np.full(row, -np.inf)

                min_prev_row = max(0, row - self.vocab.max_subword_length)
                for prev_row in range(min_prev_row, row):
                    prev_subword = token[prev_row:row]
                    if prev_subword not in self.vocab:
                        continue
                    if score_table[prev_row, row - 1] == -np.inf:
                        continue
                    bigram_score = (
                        self.estimator(subword, prev_subword) +
                        score_table[prev_row, row - 1])

                    predecesor_scores[prev_row] = bigram_score
                    if bigram_score > best_predecesor[0]:
                        best_predecesor = (bigram_score, prev_row)

                assert best_predecesor[0] == max(predecesor_scores)

                if sample and best_predecesor[0] > -np.inf:
                    predecesor_scores /= self.temperature
                    normalized_scores = np.exp(
                        predecesor_scores - logsumexp(predecesor_scores))

                    rng = np.random.default_rng()
                    selected_index = np.argmax(
                        rng.multinomial(1, normalized_scores))

                    prev_rows[row, col] = selected_index
                    score_table[row, col] = predecesor_scores[selected_index]

                else:
                    prev_rows[row, col] = best_predecesor[1]
                    score_table[row, col] = best_predecesor[0]

        subword_end = len(token)
        row = score_table[:, -1].argmax()
        segmentation = []

        while subword_end > 0:
            subword_begin = row
            subword = token[subword_begin:subword_end]
            if self.is_bert_wordpiece and subword_begin > 0:
                subword = "##" + subword
            segmentation.append(subword)

            row = prev_rows[row, subword_end - 1]
            subword_end = subword_begin

        tokenization = list(reversed(segmentation))
        self._cache[token] = tokenization
        return tokenization

    def extract_bigrams(self, tokens):
        bigrams = []
        for token in tokens:
            segmentation = list(self.segment(token, sample=True))
            bigrams.append(["###", segmentation[0]])
            for i in range(len(segmentation) - 1):
                bigrams.append(segmentation[i:i + 2])
            bigrams.append((segmentation[-1], "###"))
        return bigrams

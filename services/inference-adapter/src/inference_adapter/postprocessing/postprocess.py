from __future__ import annotations

PUNCTUATION_CUT_CHARS = {".", ",", "?", "!", ";", ":"}


class HypothesisBuffer:
    def __init__(self):
        """Initialize state for stable, buffered, and newly received hypotheses."""
        self.stable = []  # stable hypothesis
        self.buffer = []  # unstable hypothesis
        self.new = []  # new hypothesis

        self.last_stable_time = 0  # timestamp of the last stable word
        self.last_stable_word = None  # last stable word

        self.last_sentence_time = 0  # timestamp of the last word of the last sentence
        self.last_sentence_word = None  # last word of the last sentence

    def insert(self, new, offset, fudge_factor=0.1, n_gram=5):
        """
        Insert a new timestamped hypothesis into the rolling buffer.

        Args:
                new: Iterable of (start, end, token) tuples from the latest decode step.
                offset: Time offset added to each start/end timestamp.
                fudge_factor: Tolerance used when filtering words near the stable boundary.
                n_gram: Maximum n-gram size used to remove duplicated overlap.
        """

        new = [(a + offset, b + offset, t) for a, b, t in new]  # adjust the offest to match the audio

        # compare self.stable and new.
        # It inserts only the words in new that extend the stable,
        # it means they are roughly behind last_stable_time and new in content
        # the new tail is added to self.new
        self.new = [(a, b, t) for a, b, t in new if a > self.last_stable_time - fudge_factor]

        if not self.stable:
            return

        if len(self.new) < 1:
            return

        a, _, _ = self.new[0]

        if abs(a - self.last_stable_time) >= 1:  # handle only related hypotheses
            return

        # it's going to search for 1, 2, ..., 5 consecutive words (n-grams)
        # that are identical in stable and new.
        # If they are, they're dropped.
        cn = len(self.stable)  # number of stable words
        nn = len(self.new)  # number of hypothesis words

        # this loop check i-gram for i in ~[1, ..., n_gram]
        # if cn, or nn is less than n, then it's cut to the min between the three
        for i in range(1, min(cn, nn, n_gram) + 1):
            c = " ".join([self.stable[-j][2] for j in range(1, i + 1)][::-1])
            tail = " ".join(self.new[j - 1][2] for j in range(1, i + 1))

            if c == tail:
                for _ in range(i):
                    self.new.pop(0)
                break

    def flush(self):
        """Promote matching prefix tokens to stable and return that stable chunk."""
        # returns stable chunk = the longest common prefix of 2 last inserts.

        stable = []
        while self.new:
            na, nb, nt = self.new[0]

            if len(self.buffer) == 0:
                break

            if nt != self.buffer[0][2]:
                break

            stable.append((na, nb, nt))
            self.last_stable_word = nt
            self.last_stable_time = nb
            self.buffer.pop(0)
            self.new.pop(0)

        self.buffer = self.new
        self.new = []
        self.stable.extend(stable)
        return stable

    def cut(self, offset: float) -> float:
        if not self.stable:
            return 0.0

        for i in range(len(self.stable) - 1, -1, -1):
            word = str(self.stable[i][2]).strip()
            b = self.stable[i][1]

            if b < offset:
                break

            if word and word[-1] in PUNCTUATION_CUT_CHARS and offset < b:
                self.last_sentence_time = b
                self.last_sentence_word = word

                audio_cut_ts = b - offset

                return audio_cut_ts

        return 0.0

    def pop_stable(self, time):
        """Discard stable tokens whose end time is less than or equal to ``time``."""
        while self.stable and self.stable[0][1] <= time:
            self.stable.pop(0)

    def complete(self):
        """Return the current unstable hypothesis buffer (latest incomplete segment)."""
        return self.buffer

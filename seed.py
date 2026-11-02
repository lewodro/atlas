"""Seed the vault with starter facts.

    uv run python seed.py

These are guesses about you. Edit them, or delete them, once you know what
is actually true. A wrong note is worse than no note.
"""

import memory

SEEDS = [
    ("The user is learning computer science and engineering.", ["learning"]),
    ("The user writes Python and is a beginner programmer.", ["learning", "python"]),
    ("The user owns an 8 GB M1 MacBook and a Windows laptop with an RTX 2060 GPU.", ["hardware"]),
    ("The user prefers short, direct answers with no filler.", ["preference"]),
    ("The user's projects live in ~/dev.", ["setup"]),
]


def main() -> None:
    for text, tags in SEEDS:
        print("wrote", memory.remember(text, tags).name)
    print(f"\n{len(memory.note_paths())} notes in {memory.NOTES}")
    print("next: uv run python eval/run_eval.py")


if __name__ == "__main__":
    main()

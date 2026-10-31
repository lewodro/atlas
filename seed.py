"""Seed the vault with a few facts so retrieval and eval have something to chew.

    uv run python seed.py

Edit these to be true about you -- they're placeholders, not gospel.
"""

import memory

SEEDS = [
    ("I am learning Python as a beginner programmer.", ["python", "learning"]),
    ("My coding projects live in ~/dev on this Mac.", ["setup"]),
    ("I use VS Code as my editor.", ["setup", "tools"]),
    ("I am building a 'second brain' harness in ~/dev/brain.", ["python", "project"]),
    ("I prefer short, direct answers with no filler.", ["preference"]),
]


def main() -> None:
    for text, tags in SEEDS:
        path = memory.remember(text, tags)
        print("wrote", path.name)
    print(f"\n{len(memory.note_paths())} notes in {memory.NOTES}")
    print("next:  uv run python eval/run_eval.py")


if __name__ == "__main__":
    main()

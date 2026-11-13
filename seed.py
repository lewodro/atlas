<<<<<<< HEAD
"""Seed the vault with starter facts.

    uv run python seed.py

These are guesses about you. Edit them, or delete them, once you know what
is actually true. A wrong note is worse than no note.
=======
"""Seed the vault with a few facts so retrieval and eval have something to chew.

    uv run python seed.py

Edit these to be true about you -- they're placeholders, not gospel.
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
"""

import memory

SEEDS = [
<<<<<<< HEAD
    ("The user is learning computer science and engineering.", ["learning"]),
    ("The user writes Python and is a beginner programmer.", ["learning", "python"]),
    ("The user owns an 8 GB M1 MacBook and a Windows laptop with an RTX 2060 GPU.", ["hardware"]),
    ("The user prefers short, direct answers with no filler.", ["preference"]),
    ("The user's projects live in ~/dev.", ["setup"]),
=======
    ("I am learning Python as a beginner programmer.", ["python", "learning"]),
    ("My coding projects live in ~/dev on this Mac.", ["setup"]),
    ("I use VS Code as my editor.", ["setup", "tools"]),
    ("I am building a 'second brain' harness in ~/dev/brain.", ["python", "project"]),
    ("I prefer short, direct answers with no filler.", ["preference"]),
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
]


def main() -> None:
    for text, tags in SEEDS:
<<<<<<< HEAD
        print("wrote", memory.remember(text, tags).name)
    print(f"\n{len(memory.note_paths())} notes in {memory.NOTES}")
    print("next: uv run python eval/run_eval.py")
=======
        path = memory.remember(text, tags)
        print("wrote", path.name)
    print(f"\n{len(memory.note_paths())} notes in {memory.NOTES}")
    print("next:  uv run python eval/run_eval.py")
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe


if __name__ == "__main__":
    main()

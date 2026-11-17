"""Legacy seed command.

    uv run python seed.py

Public installs must not begin with guessed personal facts. Use `atlas
remember` for explicit facts or simply talk to Atlas and let the guarded
librarian write them.
"""


def main() -> None:
    print("Atlas no longer writes guessed seed memories.")
    print('Add a fact with: atlas remember "I am learning Rust."')
    print("Or start `atlas` and introduce yourself naturally.")


if __name__ == "__main__":
    main()

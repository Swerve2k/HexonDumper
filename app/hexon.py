import sys


def run():
    if "--remove-all" in sys.argv:
        from hexon_profiles import remove_all
        return remove_all()
    from hexon_app import main
    main()
    return 0


if __name__ == "__main__":
    sys.exit(run())

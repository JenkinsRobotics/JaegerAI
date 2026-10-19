"""Native multimodal diagnostics; legacy Qt windows are archived."""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--audio', choices=('plain', 'structured', 'quasi', 'full'), default='structured')
    args = parser.parse_args(argv)
    if args.check:
        from .preflight import check
        return check(audio_mode=args.audio)
    print('The legacy multimodal window is archived. Use the canonical Mac shell for dictation and speech. Camera/ambient multimodal UI integration is not implemented there yet.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Local-only invitation/account administration; never exposed over HTTP."""
import argparse
from src.mini.config import Settings
from src.mini.identity import Registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    invitation = commands.add_parser('invite')
    invitation.add_argument('--hours', type=int, default=48)
    disable = commands.add_parser('disable')
    disable.add_argument('user_id')
    args = parser.parse_args()
    registry = Registry(Settings.from_env())
    if args.command == 'invite':
        print(registry.invitation(args.hours))
    elif args.command == 'disable':
        registry.disable(args.user_id)
        print('Account disabled; sessions revoked. Existing bounded tasks are not cancelled.')


if __name__ == '__main__':
    main()

"""Run the API or an isolated demo; LAN sharing requires an explicit opt-in."""
import argparse
from ipaddress import ip_address, ip_network
from pathlib import Path
import tempfile


def private_lan_host(host):
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.version == 4 and any(address in ip_network(network) for network in
                                       ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def validate_binding(host, *, demo, lan_demo):
    if lan_demo and (not demo or not private_lan_host(host)):
        raise ValueError('--lan-demo requires --demo and one explicit RFC1918 IPv4 address; wildcard/public binding is not allowed')
    if demo and not lan_demo and host not in {'127.0.0.1', '::1'}:
        raise ValueError('Demo defaults to loopback; use --lan-demo with one private LAN interface to share fictional data')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8540)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--lan-demo', action='store_true', help='Explicitly share fictional demo on the private IPv4 supplied by --host')
    args = parser.parse_args()
    try:
        validate_binding(args.host, demo=args.demo, lan_demo=args.lan_demo)
    except ValueError as error:
        parser.error(str(error))
    from src.mini.api import create_app
    from src.mini.config import Settings
    import uvicorn
    if args.demo:
        with tempfile.TemporaryDirectory(prefix='researchpilot-mobile-demo-') as directory:
            settings = Settings(root=Path(directory), mode='demo', lan_demo=args.lan_demo)
            uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=False, access_log=False)
    else:
        uvicorn.run(create_app(Settings.from_env()), host=args.host, port=args.port, proxy_headers=False, access_log=False)


if __name__ == '__main__':
    main()

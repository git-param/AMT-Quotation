"""Production WSGI entry point: python -m backend.scalability.serve."""
import argparse

from backend.app import create_app


def main():
    parser = argparse.ArgumentParser(description='Serve AMT Quotation with Waitress.')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5062)
    parser.add_argument('--threads', type=int, default=16)
    parser.add_argument('--connection-limit', type=int, default=256)
    args = parser.parse_args()
    if args.threads < 1 or args.connection_limit < args.threads:
        parser.error('--threads must be positive and --connection-limit must be at least --threads')
    from waitress import serve
    serve(create_app(), host=args.host, port=args.port, threads=args.threads,
          connection_limit=args.connection_limit)


if __name__ == '__main__':
    main()

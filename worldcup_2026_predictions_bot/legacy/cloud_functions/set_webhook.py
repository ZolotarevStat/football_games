from __future__ import annotations

import argparse
import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    response = requests.post(
        f"https://api.telegram.org/bot{args.token}/setWebhook",
        json={"url": args.url},
        timeout=10,
    )
    response.raise_for_status()
    print(response.text)


if __name__ == "__main__":
    main()

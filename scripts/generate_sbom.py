"""Generate a deterministic SPDX 2.3 SBOM from the locked Python environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image")
    args = parser.parse_args()

    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages = [
        {
            "SPDXID": f"SPDXRef-Package-{index}",
            "name": item["name"],
            "versionInfo": item.get("version", "0.1.0"),
            "downloadLocation": item.get("source", {}).get("registry", "NOASSERTION"),
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
        for index, item in enumerate(lock["package"], start=1)
    ]
    if args.image:
        image_id = os.environ.get("TOOLWATCH_IMAGE_ID")
        if image_id is None:
            image_id = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", args.image],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        packages.insert(
            0,
            {
                "SPDXID": "SPDXRef-ContainerImage",
                "name": args.image,
                "versionInfo": "0.1.0",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": image_id.removeprefix("sha256:"),
                    }
                ],
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "Apache-2.0",
                "copyrightText": "Copyright 2026 Michael Kovalev (ohhaus) <ohhaus84@gmail.com>",
            },
        )
    namespace_seed = json.dumps(
        [(package["name"], package["versionInfo"]) for package in packages],
        separators=(",", ":"),
    )
    document_name = "toolwatch-container" if args.image else "toolwatch-python"
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": document_name,
        "documentNamespace": (
            "https://toolwatch.local/spdx/" + hashlib.sha256(namespace_seed.encode()).hexdigest()
        ),
        "creationInfo": {
            "created": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: ToolWatch-SBOM-Generator-0.1.0"],
        },
        "packages": packages,
        "annotations": (
            [
                {
                    "annotationDate": datetime.now(UTC)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "annotationType": "OTHER",
                    "annotator": "Tool: ToolWatch-SBOM-Generator-0.1.0",
                    "comment": f"Container image reference: {args.image}",
                }
            ]
            if args.image
            else []
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

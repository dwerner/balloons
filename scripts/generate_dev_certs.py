#!/usr/bin/env python3
"""Generate self-signed certificates for development.

This script creates a self-signed certificate and private key for local
development with the WebSocket server. The certificates are NOT suitable
for production use.

Usage:
    python scripts/generate_dev_certs.py [output_dir]

The output directory defaults to ~/.balloons/certs/

Files created:
    - dev.crt: Self-signed certificate (PEM format)
    - dev.key: Private key (PEM format)
"""

import argparse
import datetime
import os
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print("Error: cryptography package required. Install with:")
    print("  pip install cryptography")
    sys.exit(1)


def generate_self_signed_cert(
    output_dir: Path,
    hostname: str = "localhost",
    days_valid: int = 365,
) -> tuple[Path, Path]:
    """Generate a self-signed certificate and private key.

    Args:
        output_dir: Directory to write certificate files
        hostname: Hostname for the certificate (default: localhost)
        days_valid: Number of days the certificate is valid

    Returns:
        Tuple of (cert_path, key_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Development"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Balloons Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])

    # Build certificate
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days_valid))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(hostname),
                x509.DNSName("127.0.0.1"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    # Write private key
    key_path = output_dir / "dev.key"
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    # Set restrictive permissions on private key
    os.chmod(key_path, 0o600)

    # Write certificate
    cert_path = output_dir / "dev.crt"
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate self-signed certificates for development"
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=str(Path.home() / ".balloons" / "certs"),
        help="Output directory (default: ~/.balloons/certs/)",
    )
    parser.add_argument(
        "--hostname",
        default="localhost",
        help="Hostname for the certificate (default: localhost)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Days until certificate expires (default: 365)",
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser()

    print(f"Generating self-signed certificate for {args.hostname}...")
    print(f"Output directory: {output_dir}")

    cert_path, key_path = generate_self_signed_cert(
        output_dir=output_dir,
        hostname=args.hostname,
        days_valid=args.days,
    )

    print(f"\nGenerated files:")
    print(f"  Certificate: {cert_path}")
    print(f"  Private key: {key_path}")

    print(f"\nTo use in config.yaml:")
    print(f"""
websocket:
  host: localhost
  port: 8765
  tls:
    enabled: true
    cert_path: {cert_path}
    key_path: {key_path}
""")

    print("NOTE: Self-signed certificates will show browser warnings.")
    print("      For production, use certificates from a trusted CA.")


if __name__ == "__main__":
    import ipaddress  # Import here to fail fast at top if cryptography missing
    main()

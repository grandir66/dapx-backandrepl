#!/usr/bin/env python3
"""
Script per generare certificati SSL auto-firmati per DAPX-backandrepl
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    import ipaddress
except ImportError:
    print("Errore: libreria 'cryptography' non installata")
    print("Installa con: pip install cryptography")
    sys.exit(1)


def generate_self_signed_cert(
    cert_dir: str = None,
    hostname: str = "localhost",
    ip_addresses: list = None,
    days_valid: int = 365,
    key_size: int = 2048
):
    """
    Genera un certificato SSL auto-firmato.
    
    Args:
        cert_dir: Directory dove salvare i certificati (default: ./certs)
        hostname: Hostname per il certificato
        ip_addresses: Lista di IP da includere nel SAN
        days_valid: Giorni di validità
        key_size: Dimensione chiave RSA
    
    Returns:
        Tuple (cert_path, key_path)
    """
    
    # Directory certificati
    if cert_dir is None:
        cert_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "certs")
    
    Path(cert_dir).mkdir(parents=True, exist_ok=True)
    
    cert_path = os.path.join(cert_dir, "server.crt")
    key_path = os.path.join(cert_dir, "server.key")
    
    # Genera chiave privata RSA
    print(f"Generazione chiave RSA {key_size} bit...")
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend()
    )
    
    # Subject e Issuer (auto-firmato)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IT"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Italia"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Server"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DAPX-backandrepl"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Self-Signed"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])
    
    # Subject Alternative Names (SAN)
    san_list = [
        x509.DNSName(hostname),
        x509.DNSName("localhost"),
    ]
    
    # Aggiungi IP addresses
    if ip_addresses:
        for ip in ip_addresses:
            try:
                san_list.append(x509.IPAddress(ipaddress.ip_address(ip)))
            except ValueError:
                print(f"  Attenzione: IP non valido ignorato: {ip}")
    
    # Aggiungi sempre localhost IPs
    san_list.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    san_list.append(x509.IPAddress(ipaddress.ip_address("::1")))
    
    # Genera certificato
    print(f"Generazione certificato per {hostname}...")
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=days_valid))
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256(), default_backend())
    )
    
    # Salva chiave privata
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    os.chmod(key_path, 0o600)  # Solo proprietario può leggere
    
    # Salva certificato
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    print(f"\n✓ Certificato generato con successo!")
    print(f"  Certificato: {cert_path}")
    print(f"  Chiave:      {key_path}")
    print(f"  Validità:    {days_valid} giorni")
    print(f"  Hostname:    {hostname}")
    
    return cert_path, key_path


def check_cert_valid(cert_path: str) -> tuple:
    """
    Verifica se un certificato è valido e non scaduto.
    
    Returns:
        Tuple (is_valid, days_remaining, error_message)
    """
    try:
        with open(cert_path, "rb") as f:
            cert_data = f.read()
        
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        
        now = datetime.utcnow()
        
        if now < cert.not_valid_before:
            return False, 0, "Certificato non ancora valido"
        
        if now > cert.not_valid_after:
            return False, 0, "Certificato scaduto"
        
        days_remaining = (cert.not_valid_after - now).days
        
        return True, days_remaining, None
        
    except Exception as e:
        return False, 0, str(e)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Genera certificato SSL auto-firmato")
    parser.add_argument("--hostname", default="localhost", help="Hostname per il certificato")
    parser.add_argument("--ip", action="append", help="IP da aggiungere al SAN (può essere ripetuto)")
    parser.add_argument("--days", type=int, default=365, help="Giorni di validità")
    parser.add_argument("--output", default=None, help="Directory output")
    parser.add_argument("--check", help="Verifica certificato esistente")
    
    args = parser.parse_args()
    
    if args.check:
        valid, days, error = check_cert_valid(args.check)
        if valid:
            print(f"✓ Certificato valido, scade tra {days} giorni")
        else:
            print(f"✗ Certificato non valido: {error}")
        sys.exit(0 if valid else 1)
    
    generate_self_signed_cert(
        cert_dir=args.output,
        hostname=args.hostname,
        ip_addresses=args.ip,
        days_valid=args.days
    )


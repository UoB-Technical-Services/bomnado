#!/usr/bin/env python3
"""
Generate a secure Django secret key.

This script generates a cryptographically secure secret key suitable for
Django production environments.
"""

import argparse
import secrets
import string

def generate_secret_key(length=50):
    """
    Generate a secure Django secret key.
    
    Args:
        length (int): Length of the secret key (default: 50)
    
    Returns:
        str: A secure random string suitable for Django SECRET_KEY
    """
    # Define the character set for the secret key
    # Django secret keys can contain letters, digits, and these special characters
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
    
    # Generate a cryptographically secure random string
    secret_key = ''.join(secrets.choice(alphabet) for _ in range(length))
    
    return secret_key

def main():
    """Main function to generate and display secret keys."""
    parser = argparse.ArgumentParser(description='Generate a secure Django secret key')
    parser.add_argument('--env', action='store_true', 
                       help='Output only the 64-character key for appending to .env file')
    parser.add_argument('--output', '-o', type=str,
                       help='Write the key directly to a file (e.g., .env)')
    args = parser.parse_args()
    
    if args.env:
        # Just output the key for .env file
        key_64 = generate_secret_key(64)
        print(f"DJANGO_SECRET_KEY={key_64}")
        return
    
    if args.output:
        # Write directly to file with proper encoding
        key_64 = generate_secret_key(64)
        try:
            with open(args.output, 'a', encoding='utf-8') as f:
                f.write(f"DJANGO_SECRET_KEY={key_64}\n")
            print(f"✅ Secret key appended to {args.output}")
        except Exception as e:
            print(f"❌ Error writing to file: {e}")
        return
    
    print("🔐 Django Secret Key Generator")
    print("=" * 40)
    
    # Generate keys of different lengths
    key_50 = generate_secret_key(50)
    key_64 = generate_secret_key(64)
    
    print(f"\n50-character key (recommended minimum):")
    print(f"DJANGO_SECRET_KEY={key_50}")
    
    print(f"\n64-character key (extra secure):")
    print(f"DJANGO_SECRET_KEY={key_64}")
    
    print(f"\n📝 Instructions:")
    print(f"1. Copy one of the keys above")
    print(f"2. Replace the DJANGO_SECRET_KEY value in your .env file")
    print(f"3. Use a different key for each environment (dev, staging, prod)")
    print(f"4. Never share or commit secret keys to version control")
    
    print(f"\n⚠️  Important Notes:")
    print(f"- Keep this key secret and secure")
    print(f"- Use different keys for different environments")
    print(f"- Changing the key will invalidate all existing sessions")
    print(f"- Store production keys in secure environment variables")

if __name__ == '__main__':
    main()

import hashlib
import pandas as pd
import argparse

def pin_hash(pin: str, salt: str = "") -> str:
    return hashlib.sha256((salt + str(pin)).encode()).hexdigest()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hash PINs from Members CSV and write PIN_Hash column")
    parser.add_argument("--infile", required=True, help="Path to members CSV with PIN column")
    parser.add_argument("--outfile", required=True, help="Where to write the output CSV")
    parser.add_argument("--salt", default="", help="Optional salt string (should match secrets.security.pin_salt)")
    args = parser.parse_args()

    df = pd.read_csv(args.infile)
    if "PIN" not in df.columns:
        raise SystemExit("No 'PIN' column found.")
    df["PIN_Hash"] = df["PIN"].apply(lambda x: pin_hash(x, args.salt))
    # Remove the plain PIN if you want:
    # df = df.drop(columns=["PIN"])
    df.to_csv(args.outfile, index=False)
    print(f"Wrote {args.outfile}")

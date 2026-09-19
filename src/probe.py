"""Step 1 + Step 2: slug test, robots check, and year -> gallery URL discovery."""
import httpx

HEAD = {
    "User-Agent": "HTN2026-student-research/1.0 "
                  "(+https://github.com/richashah29/Hack-the-North-26)"
}
client = httpx.Client(headers=HEAD, timeout=25, follow_redirects=True)


def robots():
    for host in ["https://devpost.com", "https://museum.hackthenorth.com"]:
        try:
            r = client.get(f"{host}/robots.txt")
            print(f"=== {host}/robots.txt ({r.status_code}) ===")
            print(r.text[:1500])
        except Exception as e:
            print("ERR", host, e)
        print()


def slug_test():
    print("=== Step 1: slug test ===")
    for slug in ["chessmate-nwygvq", "pulsegrip", "dejavu", "spyder"]:
        try:
            r = client.get(f"https://devpost.com/software/{slug}")
            print(f"{slug:24} {r.status_code}  -> {r.url}")
        except Exception as e:
            print(f"{slug:24} ERR {e}")
    print()


def years():
    print("=== Step 2: year gallery discovery ===")
    found = {}
    candidates = [(2014, "https://hackthenorth.devpost.com")]
    candidates += [(y, f"https://hackthenorth{y}.devpost.com") for y in range(2015, 2027)]
    for y, base in candidates:
        try:
            r = client.get(f"{base}/project-gallery")
            if r.status_code == 200:
                found[y] = base
                print(f"OK   {y}  {base}  -> {r.url}")
            else:
                print(f"MISS {y}  {base}  {r.status_code}")
        except Exception as e:
            print(f"ERR  {y}  {base}  {type(e).__name__}: {e}")
    print()
    print("found:", found)
    return found


if __name__ == "__main__":
    robots()
    slug_test()
    years()

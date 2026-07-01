"""
Teste jusqu'à quelle taille genereImage.html génère une image unique.
Détermine si la voie A (image plus grande) est viable et à quelle résolution max.
"""
import requests, urllib3
urllib3.disable_warnings()

BASE          = "https://archives.cotedor.fr"
DATA_ORIGINAL = "/mnt/lustre/ad21/num_ext/frad021_3p/frad021_3p_plan_004/frad021_3p_plan_004_001.jpg"
# Original = 8015 x 5457

s = requests.Session()
s.verify = False
s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/128.0"
s.headers["Accept-Encoding"] = "gzip, deflate"

sizes = [1080, 2000, 3000, 4000, 6000, 8015, 10000]

print(f"{'demandé':>8}  {'code':>4}  {'thumb WxH':>12}  {'orig WxH':>12}  {'cache KB':>9}  URL")
for size in sizes:
    params = {"l": size, "h": size, "r": 0, "n": 0, "b": 0, "c": 0,
              "o": "IMG", "id": "visu_image_1", "image": DATA_ORIGINAL}
    r = s.get(f"{BASE}/v2/images/genereImage.html", params=params, timeout=45)
    parts = r.text.strip().split("\t")
    if len(parts) >= 6:
        code, src, tw, th, iw, ih = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        # Récupère la taille réelle du fichier cache
        rc = s.get(BASE + src, timeout=45, stream=True)
        magic = rc.raw.read(3).hex().upper()
        cl = rc.headers.get("Content-Length", "?")
        rc.close()
        kb = f"{int(cl)//1024}" if cl.isdigit() else cl
        jpeg = "JPEG" if magic.startswith("FFD8FF") else "!!"
        # nom cache pour voir quelle taille est réellement encodée
        cache_size = src.split("_")[-6:-4]  # ..._{L}_{H}_0_0_0_0_img.jpg
        print(f"{size:>8}  {code:>4}  {tw+'x'+th:>12}  {iw+'x'+ih:>12}  {kb:>9}  {jpeg} cache_dims={cache_size}")
    else:
        print(f"{size:>8}  ERREUR: {r.text[:80]}")

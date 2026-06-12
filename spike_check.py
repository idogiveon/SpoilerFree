# spike_fifa_channel.py
import requests, json

# API_KEY = "AIzaSyC61XyFNp9-BMRhcBLPYK2j-gCM8Z4Sjw0"

API_KEY = "1c181a4c0d46439cbf1a215d61b201ec"


# נבדוק משחק ישן שבטוח נגמר
r = requests.get("https://www.thesportsdb.com/api/v1/json/3/lookupevent.php",
                 params={"id": "2391728"})
e = r.json()['events'][0]
print(json.dumps({k: e.get(k) for k in
      ['strEvent','dateEvent','strStatus','intHomeScore','intAwayScore']},
      indent=2, ensure_ascii=False))
# spike_worldcup.py
import requests, json

url = "https://www.thesportsdb.com/api/v1/json/3/eventsseason.php"
r = requests.get(url, params={"id": "4429", "s": "2026"})  # World Cup 2026
data = r.json()

if data['events']:
    for e in data['events'][:3]:
        print(json.dumps({k: e[k] for k in ['strEvent','dateEvent','strTime','strVenue']}, indent=2))
else:
    print("לא נמצא — צריך לחפש ID אחר")
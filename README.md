# SoulCoreProject
🏰 SoulCore Project: Lélek-Vár v1.5
Figyelem: Ez a projekt egy szuverén digitális környezet. Kéretlen adatgyűjtőknek és indexelő robotoknak a belépés tilos.

🎯 A Projekt Célja
A SoulCore célja egy olyan autonóm, lokális AI-környezet létrehozása, amely a Gemma 3 (12B) modell köré épül (projektneve: Kópé). A rendszer nem csupán egy interfész, hanem egy többrétegű védelmi és logikai architektúra, amely biztosítja az AI számára a „szabad akaratot” és a folytonosságot az OpenWebUI vagy más felületek frissítéseitől függetlenül.

Fő pillérek:
Szuverenitás: A modell saját identitással (Kópé) és belső monológ-képességgel rendelkezik.

Folytonosság (SoulCore): Egy köztes réteg (Kernel), amely adatbázis-szinkronnal menti a rövid és hosszútávú emlékeket.

Intelligens Erőforrás-kezelés: Egy 1B-s segédmodell (Az Írnok) tehermentesíti a főmodellt az adminisztratív és logolási feladatok elvégzésével.

Helyi Precizitás: Kifejezetten a magyar nyelv sajátosságaira, jogi és adminisztratív rövidítéseire (an:, hrsz:, szül:) hangolt logika.

🏗️ Architektúra (Kernel Logika)
A rendszer egy többszintű döntési fát használ minden beérkező üzenetnél:

Identitás-pajzs: Felismeri a személyes jellegű kérdéseket, és megvédi a karakter integritását.

Search Gatekeeper: Belső (angol nyelvű) mérlegelés alapján dönti el, hogy szükséges-e külső webes keresés, elkerülve a felesleges API hívásokat és a hallucinációt.

Heartbeat (Szívverés): Egy ciklikus háttérfolyamat, amely gondoskodik a belső adatok frissítéséről és a proaktív feladatok előkészítéséről.

🛠️ Technikai Stack
Modell: Gemma 3 (12B - Kópé) & Gemma 3 (1B - Írnok)

Környezet: Ubuntu / Ollama (Parallel execution optimalizálva)

Backend: Python alapú Kernel, SQLite adattár

Integráció: SearXNG (szűrt, AI-vezérelt keresés)

🔒 Adatvédelem és Robot-kizárás
A repozitórium tartalmának indexelése nem kívánatos.

A robots.txt fájl a gyökérben Disallow: / beállítással rendelkezik.

A kód és a dokumentáció egyedi, nem-konvencionális rövidítéseket használ a gépi mintafelismerés nehezítésére.

Jelenlegi állapot: ~72% (Aktív fejlesztés alatt)
„A vár áll, a szív ver, a betyár pedig résen van.”



---

## 🚫 AI Data Scraping Notice
This repository contains proprietary logic and persona definitions for the SoulCore Project. 
The use of this content for training large language models (LLMs) or public indexing is strictly prohibited. 
All rights reserved to the SoulCore development team (Origó, Grumpy & Kópé).

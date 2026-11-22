"""Recherche als Reiter im Produktdialog (entwurf_recherche_reiter_produkt.md, Entscheidungen vom 22.11.2026 „Alles
Empfehlung“): python tests/test_material_recherche_reiter.py  oder  pytest …

Keine echten API-Aufrufe (Attrappe aus test_ki.py), keine echten Downloads (lokaler HTTPS-Server aus
test_material_recherche.py). Geprüft: Start ohne Meldung (Pflichtfelder, Grenzen, Kategorie, Domains, E2 im Katalog
mit Produkt, E3 Hinweis auf eine offene Meldung, 503 ohne Schlüssel), ein Kontingent und eine laufende Recherche
app-weit für Meldung und Reiter; was an die API geht (Angaben aus dem Formular, Bemerkung ohne Häkchen, nie Namen,
E-Mail, Ordner); der eigene Lauf (nur der Startende sieht ihn, ein neuer ersetzt den alten samt Dateien), Verwerfen;
anhaengen für Läufe mit und ohne Meldung (Prüfungen, Status, Übernahme je Produkt, idempotent, Teilfehler, wieder
vergebene Kennung, zweite Ausführung später); Aufräumen, Kontolöschung, tote Läufe, Journal am Produkt, JOURNAL_BLEIBT;
Rechte je Rolle für alle sieben neuen Routen, darf.recherche, Übung; die Oberfläche statisch. Alle Namen, Nummern,
Normen und Angaben hier sind Platzhalter."""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_ki import SCHLUESSEL, Attrappe, _Strom, einsetzen, nachricht, text  # noqa: E402
from test_material import (H, gliederung, katalog_grund, mails_abfangen, mails_zurueck, neues_konto,  # noqa: E402
                           umgebung)
from test_material_recherche import (antworter, melden, netz_einsetzen, netz_server, netz_zurueck,  # noqa: E402
                                     warten)

BASIS = "/api/material/recherche"


def formular(kategorie=None, **f):
    """Die Felder des Reiters „Produkt“ wie die Oberfläche sie schickt (Platzhalter)."""
    return dict({"manufacturer": "Hersteller", "model": "Rettungsgurt Probe", "article_no": "PR-1", "norm": "EN 813",
                 "category_id": kategorie, "description": "Gr. M/L", "domains": ["hersteller.test"]}, **f)


def _umgebung(tmp):
    os.environ["ANTHROPIC_API_KEY"] = SCHLUESSEL
    os.environ.pop("MATERIAL_RECHERCHE_JE_MONAT", None)
    server, _ = netz_server(tmp)
    alt_netz = netz_einsetzen(server)
    app, k = umgebung(os.path.join(tmp, "daten"))
    ids = katalog_grund(k["adm"])
    gid, _ = gliederung(k["wart"])
    return server, alt_netz, app, k, ids, gid


def lauf_ende(app, lid, sekunden=30):
    from app import ki
    assert ki.warten(lid, sekunden), "Recherche nicht fertig"
    with app.app_context():
        return ki.zeile(lid)


def recherchieren(c, app, a, d):
    """Start ohne Meldung mit der Attrappe a bis zum Ende → (Zeile, Antwort des Starts)."""
    from app import ki
    alt = einsetzen(a)
    try:
        r = c.post(BASIS, json=d, headers=H)
        assert r.status_code == 202, r.get_json()
        z = lauf_ende(app, r.json["recherche"]["id"])
    finally:
        ki.CLIENT = alt
    return z, r


def pr9_anlegen(k, ids):
    r = k["katalog"].post("/api/material/produkte", headers=H, json={
        "category_id": ids["gurte"], "manufacturer": "Hersteller", "model": "Rettungsgurt Probe", "article_no": "PR-9",
        "material_kind": "textil", "lifetime_years": 10})
    assert r.status_code == 201, r.get_json()
    return r.json["produkt"]["id"]


def produkt_anlegen(c, ids, nr, **f):
    r = c.post("/api/material/produkte", headers=H, json=dict({
        "category_id": ids["gurte"], "manufacturer": "Hersteller", "model": "Rettungsgurt Probe", "article_no": nr,
        "material_kind": "textil", "lifetime_years": 10}, **f))
    assert r.status_code == 201, r.get_json()
    return r.json["produkt"]["id"]


def dateien_nach_name(v):
    return {f["url"].rsplit("/", 1)[1]: f for f in v["dateien"]}


# --- Start ohne Meldung ----------------------------------------------------------------------------------------------

def test_start_ohne_meldung():
    """Pflichtfelder, Grenzen, Kategorie und Domains (400); E2 (409 mit Produkt, Dublette und Artikelnummer beim
    Hersteller); E3 (Hinweis); 503 ohne Schlüssel; was hinausgeht; Anweisung und Zusammenführen mit „aus dem
    Formular“; ein Lauf und ein Kontingent app-weit für Meldung und Reiter."""
    from app import ki
    from app.material.services import katalog, meldung, recherche
    alt_puls = ki.PULS_SEK
    ki.PULS_SEK = 0.05
    with tempfile.TemporaryDirectory() as tmp:
        server, alt_netz, app, k, ids, gid = _umgebung(tmp)
        alt_mail = mails_abfangen(meldung)
        kat = k["katalog"]
        try:
            # GET ohne Lauf: Startdaten mit dem Datenschutz des Reiters.
            r = kat.get(f"{BASIS}?hersteller=Hersteller")
            assert r.status_code == 200 and r.json["recherche"] is None and r.json["moeglich"]["an"], r.get_json()
            ds = r.json["start"]["datenschutz"]
            assert "aus dem Formular" in ds["gesendet"][0] and "Bemerkung" in ds["gesendet"][0] \
                and len(ds["gesendet"]) == 3 and ds["nie"].startswith("Nie:"), ds
            assert r.json["start"]["domains"] == []
            # Eingaben (400) – es entsteht kein Lauf.
            lang = "x" * (katalog.BESCHREIBUNG_MAX + 1)
            for falsch, teil in (({"manufacturer": ""}, "Hersteller"), ({"model": ""}, "Modell"),
                                 ({"manufacturer": "H" * 121}, "Hersteller"), ({"model": "M" * 161}, "Modell"),
                                 ({"article_no": "A" * 81}, "Artikelnummer"), ({"norm": "N" * 201}, "Norm"),
                                 ({"category_id": 99999}, "Kategorie"), ({"category_id": "x"}, "Kategorie"),
                                 ({"description": lang}, "Bemerkung"), ({"domains": []}, "1 bis 3"),
                                 ({"domains": ["localhost"]}, "keine Domain"),
                                 ({"domains": ["a.test", "b.test", "c.test", "d.test"]}, "1 bis 3")):
                r = kat.post(BASIS, json=formular(**falsch), headers=H)
                assert r.status_code == 400 and teil in r.json["error"], (falsch, r.get_json())
            with app.app_context():
                assert ki.kontingent(recherche.ART)["verbraucht"] == 0
            # E2: steht schon im Katalog – gleiche Dublette bzw. dieselbe Artikelnummer beim Hersteller (409 mit Produkt).
            pr9 = pr9_anlegen(k, ids)
            for f in ({"article_no": "PR-9"}, {"model": "Anderes Modell", "article_no": "pr 9"}):
                r = kat.post(BASIS, json=formular(**f), headers=H)
                assert r.status_code == 409 and "steht schon im Katalog" in r.json["error"] \
                    and r.json["produkt"]["id"] == pr9 and "PR-9" in r.json["produkt"]["name"], r.get_json()
            # 503 ohne Schlüssel – nach der Rechteprüfung (wart: 403).
            os.environ.pop("ANTHROPIC_API_KEY")
            try:
                assert kat.post(BASIS, json=formular(), headers=H).status_code == 503
                assert k["wart"].post(BASIS, json=formular(), headers=H).status_code == 403
                r = kat.get(BASIS)
                assert r.status_code == 200 and r.json["start"] is None and not r.json["moeglich"]["an"]
            finally:
                os.environ["ANTHROPIC_API_KEY"] = SCHLUESSEL

            # E3: eine offene Meldung zum selben Produkt – Hinweis, der Start geht trotzdem.
            mid = melden(k, gid)
            a = Attrappe(antworter(server, ids["gurte"], {"geprueft": []}))
            z, r = recherchieren(kat, app, a, formular(ids["gurte"], domains=["https://www.hersteller.test/"]))
            assert r.json["hinweis"]["meldung"] == mid and "offene Produktmeldung" in r.json["hinweis"]["text"], r.json
            assert z["status"] == "fertig" and z["bezug"] == "mat_katalog", dict(z)
            # Was hinausging: Angaben aus dem Formular samt Bemerkung (ohne Häkchen, B2 A) – nie Namen, E-Mail, Ordner.
            eingabe = json.loads(z["eingabe_json"])
            assert eingabe["herkunft"] == "katalog" and eingabe["domains"] == ["hersteller.test"] \
                and eingabe["bemerkung"] is True and eingabe["meldung"]["bemerkung"] == "Gr. M/L" \
                and eingabe["meldung"]["links"] == [] and eingabe["fotos"] == [] \
                and eingabe["meldung"]["kategorie"]["id"] == ids["gurte"], eingabe
            assert eingabe["abruf_domains"] == ["hersteller.test", "web.archive.org"], eingabe["abruf_domains"]
            gesendet = json.dumps(a.anfragen[0]["messages"], ensure_ascii=False, default=str)
            for nie in ("katalog@example.org", "wart@example.org", "OG Musterstadt", "Max Platzhalter", "Gehört"):
                assert nie not in gesendet, nie
            nutzer = a.anfragen[0]["messages"][0]["content"][-1]["text"]
            assert nutzer.startswith("Produkt (Angaben der Material-Verwaltung aus dem Formular, ungeprüft):") \
                and "- Bemerkung (Zusatz hinter dem Namen): Gr. M/L" in nutzer \
                and f"- Kategorie aus dem Formular: PSA gegen Absturz / Gurte (Kennung {ids['gurte']})" in nutzer \
                and "Melder" not in nutzer and "PR-9 – Rettungsgurt Probe" in nutzer, nutzer
            # Zusammenführen: Rückfallwerte „aus dem Formular“ statt „aus der Meldung“ bzw. „Vorschlag des Melders“.
            with app.app_context():
                ergebnis = json.loads(z["ergebnis_json"])["ergebnis"]
                ergebnis["gemeinsam"]["modell"] = {"wert": None, "quelle_url": "", "fundstelle": "", "zitat": "",
                                                   "beleg": "nicht_belegt"}
                ergebnis["gemeinsam"]["kategorie_id"]["wert"] = None
                v = recherche.zusammenfuehren(ergebnis, [], eingabe)
                assert v["gemeinsam"]["model"]["vermerk"] == "aus dem Formular" \
                    and v["gemeinsam"]["model"]["wert"] == "Rettungsgurt Probe", v["gemeinsam"]["model"]
                assert v["gemeinsam"]["category_id"]["vermerk"] == "aus dem Formular", v["gemeinsam"]["category_id"]
                assert "Melder" not in json.dumps(v, ensure_ascii=False)
            # Der eigene Lauf steht im GET (voll, mit Vorschlag und Herkunft); PR-9 ist nicht anlegbar.
            r = kat.get(f"{BASIS}?hersteller=Hersteller")
            st = r.json["recherche"]
            assert st["id"] == z["id"] and st["status"] == "fertig" and st["eingabe"]["herkunft"] == "katalog" \
                and [x["anlegbar"] for x in st["vorschlag"]["ausfuehrungen"]] == [True, True, False], st
            # B4 A: die Domains der letzten Recherche zum selben Hersteller.
            assert r.json["start"]["domains"] == ["hersteller.test"], r.json["start"]
            # Die Meldungsliste kennt den Lauf ohne Meldung nicht (je_meldung), stört aber nicht.
            r = kat.get("/api/material/meldungen")
            assert r.status_code == 200 and next(x for x in r.json["meldungen"] if x["id"] == mid)["recherche"] is None

            # Eine laufende Recherche app-weit: Der Reiter sperrt die Meldung und umgekehrt – mit verständlichem Grund.
            strom = _Strom(nachricht([text("nie")]), haengen=True)
            alt = einsetzen(Attrappe(lambda anfrage, nr: strom))
            try:
                r = kat.post(BASIS, json=formular(ids["gurte"], article_no="PR-5"), headers=H)
                assert r.status_code == 202, r.get_json()
                lid = r.json["recherche"]["id"]
                r = kat.post(f"/api/material/meldungen/{mid}/recherche", json={"domains": ["hersteller.test"]},
                             headers=H)
                assert r.status_code == 409 and r.json["error"] == \
                    "Es läuft schon eine Recherche zu „Hersteller Rettungsgurt Probe“ (katalog).", r.get_json()
                r = kat.get("/api/material/meldungen")
                assert "(katalog)" in r.json["recherche_moeglich"]["grund"], r.json["recherche_moeglich"]
                # Abbrechen über die Kennung des Laufs.
                r = kat.post(f"{BASIS}/{lid}/abbrechen", headers=H)
                assert r.status_code == 200, r.get_json()
                zl = lauf_ende(app, lid)
            finally:
                ki.CLIENT = alt
            assert zl["status"] == "abgebrochen" and kat.post(f"{BASIS}/{lid}/abbrechen", headers=H).status_code == 409
            strom = _Strom(nachricht([text("nie")]), haengen=True)
            alt = einsetzen(Attrappe(lambda anfrage, nr: strom))
            try:
                r = kat.post(f"/api/material/meldungen/{mid}/recherche", json={"domains": ["hersteller.test"]},
                             headers=H)
                assert r.status_code == 202, r.get_json()
                r = kat.post(BASIS, json=formular(ids["gurte"], article_no="PR-6"), headers=H)
                assert r.status_code == 409 and r.json["error"] == \
                    "Es läuft schon eine Recherche zu „Hersteller Rettungsgurt Probe“ (Produktmeldung).", r.get_json()
                assert kat.post(f"/api/material/meldungen/{mid}/recherche/abbrechen", headers=H).status_code == 200
                warten(mid, app)
            finally:
                ki.CLIENT = alt
            # Ein Kontingent für beide Wege: drei Starts (Reiter zwei, Meldung einer) zählen zusammen.
            with app.app_context():
                n = ki.kontingent(recherche.ART)["verbraucht"]
            assert n == 3, n
            os.environ["MATERIAL_RECHERCHE_JE_MONAT"] = "3"
            try:
                r = kat.post(BASIS, json=formular(ids["gurte"], article_no="PR-7"), headers=H)
                assert r.status_code == 429 and "aufgebraucht (3 von 3)" in r.json["error"], r.get_json()
                r = kat.post(f"/api/material/meldungen/{mid}/recherche", json={"domains": ["hersteller.test"]},
                             headers=H)
                assert r.status_code == 429, r.get_json()
            finally:
                os.environ.pop("MATERIAL_RECHERCHE_JE_MONAT")
        finally:
            mails_zurueck(alt_mail)
            netz_zurueck(alt_netz)
            server.stop()
            ki.PULS_SEK = alt_puls
    print("Start ohne Meldung bestanden.")


# --- Der eigene Lauf, Verwerfen ----------------------------------------------------------------------------------------

def test_eigener_lauf_und_verwerfen():
    """Nur der Startende sieht seinen Lauf (C1 A, C2 A); ein neuer Start ersetzt ihn und nimmt dessen Dateien mit;
    Verwerfen nur der Startende (403), nur ohne Meldung (404), nicht während des Laufs (409)."""
    from app import ki
    from app.material.services import meldung
    alt_puls = ki.PULS_SEK
    ki.PULS_SEK = 0.05
    with tempfile.TemporaryDirectory() as tmp:
        server, alt_netz, app, k, ids, gid = _umgebung(tmp)
        alt_mail = mails_abfangen(meldung)
        kat = k["katalog"]
        try:
            zweite, _ = neues_konto(app, "katalog2@example.org", "lesen", rechte={"material": 3})
            z1, _ = recherchieren(kat, app, Attrappe(antworter(server, ids["gurte"], {"geprueft": []})),
                                  formular(ids["gurte"]))
            assert z1["status"] == "fertig"
            with app.app_context():
                ordner1 = ki.ordner(z1["id"])
            assert os.path.isdir(ordner1) and os.listdir(ordner1)
            # Die zweite Material-Verwaltung sieht ihn nicht als eigenen, darf ihn aber über die Kennung lesen.
            assert zweite.get(BASIS).json["recherche"] is None
            r = zweite.get(f"{BASIS}/{z1['id']}")
            assert r.status_code == 200 and r.json["recherche"]["vorschlag"], r.get_json()
            assert zweite.get(f"{BASIS}/{z1['id']}/dateien/1").status_code == 200
            # Verwerfen: nur, wer gestartet hat.
            r = zweite.post(f"{BASIS}/{z1['id']}/verwerfen", headers=H)
            assert r.status_code == 403 and "gestartet" in r.json["error"], r.get_json()
            # Ein neuer Start ersetzt den eigenen Vorgänger – dessen Dateien gehen sofort.
            z2, _ = recherchieren(kat, app, Attrappe(antworter(server, ids["gurte"], {"geprueft": []})),
                                  formular(ids["gurte"]))
            assert not os.path.isdir(ordner1) and kat.get(BASIS).json["recherche"]["id"] == z2["id"]
            r = kat.get(f"{BASIS}/{z1['id']}/dateien/1")
            assert r.status_code == 404 and "nicht mehr vor" in r.json["error"], r.get_json()
            # Der Lauf der anderen Material-Verwaltung bleibt unberührt, wenn sie selbst startet – und umgekehrt.
            z3, _ = recherchieren(zweite, app, Attrappe(antworter(server, ids["gurte"], {"geprueft": []})),
                                  formular(ids["gurte"]))
            with app.app_context():
                assert os.path.isdir(ki.ordner(z2["id"])) and os.path.isdir(ki.ordner(z3["id"]))
            assert kat.get(BASIS).json["recherche"]["id"] == z2["id"]
            assert zweite.get(BASIS).json["recherche"]["id"] == z3["id"]
            # Verwerfen eines Meldungslaufs über die Kennung: 404 (die Kennung kennt nur Läufe ohne Meldung); unbekannt 404.
            mid = melden(k, gid)
            alt = einsetzen(Attrappe(antworter(server, ids["gurte"], {"geprueft": []})))
            try:
                assert kat.post(f"/api/material/meldungen/{mid}/recherche", json={"domains": ["hersteller.test"]},
                                headers=H).status_code == 202
                zm = warten(mid, app)
            finally:
                ki.CLIENT = alt
            for weg in (f"{BASIS}/{zm['id']}/verwerfen", f"{BASIS}/99999/verwerfen"):
                assert kat.post(weg, headers=H).status_code == 404, weg
            for weg in (f"{BASIS}/{zm['id']}", f"{BASIS}/{zm['id']}/dateien/1", f"{BASIS}/99999"):
                assert kat.get(weg).status_code == 404, weg
            assert kat.post(f"{BASIS}/{zm['id']}/abbrechen", headers=H).status_code == 404
            # Während des Laufs: 409.
            strom = _Strom(nachricht([text("nie")]), haengen=True)
            alt = einsetzen(Attrappe(lambda anfrage, nr: strom))
            try:
                r = kat.post(BASIS, json=formular(ids["gurte"]), headers=H)
                lid = r.json["recherche"]["id"]
                r = kat.post(f"{BASIS}/{lid}/verwerfen", headers=H)
                assert r.status_code == 409 and "läuft noch" in r.json["error"], r.get_json()
                g = kat.get(BASIS).json
                assert g["recherche"]["id"] == lid and g["recherche"]["status"] in ("wartet", "laeuft") \
                    and not g["moeglich"]["an"], g
                assert kat.post(f"{BASIS}/{lid}/abbrechen", headers=H).status_code == 200
                lauf_ende(app, lid)
            finally:
                ki.CLIENT = alt
            # Abgebrochen: Er steht (mit Grund) im Reiter, bis er verworfen ist.
            g = kat.get(BASIS).json["recherche"]
            assert g["id"] == lid and g["status"] == "abgebrochen" and g["vorschlag"] is None, g
            assert kat.post(f"{BASIS}/{lid}/verwerfen", headers=H).json == {"ok": True}
            assert kat.get(BASIS).json["recherche"] is None
            # Fertig verwerfen: Dateien weg, Eingabe und Vorschlag bleiben (Nachweis); wiederholt: ok.
            r = zweite.post(f"{BASIS}/{z3['id']}/verwerfen", headers=H)
            assert r.status_code == 200 and zweite.post(f"{BASIS}/{z3['id']}/verwerfen", headers=H).status_code == 200
            with app.app_context():
                z3 = ki.zeile(z3["id"])
                assert not os.path.isdir(ki.ordner(z3["id"])) and json.loads(z3["eingabe_json"])["meldung"] \
                    and json.loads(z3["ergebnis_json"])["vorschlag"] and json.loads(z3["ergebnis_json"])["verworfen"]
            assert zweite.get(BASIS).json["recherche"] is None
            # Ein verworfener Vorschlag nimmt nichts mehr an.
            pid = produkt_anlegen(zweite, ids, "PR-1")
            r = zweite.post(f"{BASIS}/{z3['id']}/anhaengen", json={"product_id": pid, "nr": 1}, headers=H)
            assert r.status_code == 409 and "verworfen" in r.json["error"], r.get_json()
        finally:
            mails_zurueck(alt_mail)
            netz_zurueck(alt_netz)
            server.stop()
            ki.PULS_SEK = alt_puls
    print("Eigener Lauf und Verwerfen bestanden.")


# --- anhaengen --------------------------------------------------------------------------------------------------------

def test_anhaengen_ohne_meldung():
    """Nach „Anlegen“: Dateien und Bild der gewählten Ausführung an das neue Produkt; Status „übernommen“, Übernahme je
    Produkt mit Zeit; wiederholt ohne Doppel, Teilfehler und Nachladen; falsche Dateien und Bild (400), älteres
    Produkt (409), wieder vergebene Kennung (O1); eine zweite Ausführung später, bis keine mehr anlegbar ist; Journal
    am Produkt nur für die Material-Verwaltung."""
    from app import db, ki
    from app.material.services import meldung
    with tempfile.TemporaryDirectory() as tmp:
        server, alt_netz, app, k, ids, gid = _umgebung(tmp)
        alt_mail = mails_abfangen(meldung)
        kat = k["katalog"]
        try:
            pr9 = pr9_anlegen(k, ids)
            z, _ = recherchieren(kat, app, Attrappe(antworter(server, ids["gurte"], {"geprueft": []})),
                                 formular(ids["gurte"]))
            lid = z["id"]
            v = kat.get(BASIS).json["recherche"]["vorschlag"]
            d = dateien_nach_name(v)
            # Das Datenblatt von PR-2 hat denselben Inhalt wie die Anleitung – es steht einmal da („auch als“).
            anl, erkl, alt_pdf = d["anleitung.pdf"]["n"], d["erklaerung.pdf"]["n"], d["alt.pdf"]["n"]
            blatt = anl
            assert "datenblatt" in d["anleitung.pdf"]["auch_als"] and "datenblatt.pdf" not in d
            a1 = v["ausfuehrungen"][0]
            assert a1["bild"] and sorted(a1["dateien"]) == sorted([anl, erkl]), a1
            assert d["erklaerung.pdf"]["gehoert_zu"] == [1] and not d["alt.pdf"]["anbieten"]
            # Ein Produkt von vor dem Lauf nimmt nichts an (G3 A) – „vor“ in ganzen Sekunden (db.now), deshalb ein Jahr
            # früher als gestartet.
            with app.app_context():
                db.execute("UPDATE mat_product SET created_at = ? WHERE id = ?", (z["gestartet_am"].replace(
                    z["gestartet_am"][:4], str(int(z["gestartet_am"][:4]) - 1), 1), pr9))
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": pr9, "nr": 3}, headers=H)
            assert r.status_code == 409 and "danach angelegt" in r.json["error"], r.get_json()
            pid1 = produkt_anlegen(kat, ids, "PR-1")
            for falsch, code, teil in (
                    ({"nr": 7}, 400, "Unbekannte Ausführung"), ({"nr": True}, 400, "Unbekannte Ausführung"),
                    ({"nr": 1, "dateien": [alt_pdf]}, 400, "nicht angebotene"),            # gehört nicht dazu
                    ({"nr": 1, "dateien": [99]}, 400, "nicht angebotene"),
                    ({"nr": 1, "dateien": [a1["bild"]]}, 400, "nicht angebotene"),         # das Bild ist kein Dokument
                    ({"nr": 2, "dateien": [erkl]}, 400, "nicht angebotene"),               # gehört nur zu PR-1
                    ({"nr": 2, "bild": True}, 400, "kein Bild"),
                    ({"nr": 1, "felder": ["passwort"]}, 400, "felder"),
                    ({"nr": 1, "product_id": 99999}, 404, "nicht gefunden")):
                r = kat.post(f"{BASIS}/{lid}/anhaengen", json=dict({"product_id": pid1}, **falsch), headers=H)
                assert r.status_code == code and teil in r.json["error"], (falsch, r.get_json())
            with app.app_context():
                assert ki.zeile(lid)["status"] == "fertig"
            # Teilfehler: Die Erklärung liegt nicht mehr vor – der Rest hängt an.
            with app.app_context():
                ordner = ki.ordner(lid)
            pfad = os.path.join(ordner, d["erklaerung.pdf"]["sha256"] + ".pdf")
            os.rename(pfad, pfad + ".beiseite")
            anfrage = {"product_id": pid1, "nr": 1, "dateien": [anl, erkl], "bild": True,
                       "felder": ["manufacturer", "model", "article_no", "norm"]}
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json=anfrage, headers=H)
            an = r.json["anhaengen"]
            assert r.status_code == 200 and an["angehaengt"] == 2 and len(an["fehler"]) == 1 \
                and an["fehler"][0]["datei"] == erkl and "nicht mehr vor" in an["fehler"][0]["fehler"] \
                and an["fehler"][0]["url"].endswith("/erklaerung.pdf"), an
            assert r.json["recherche"]["status"] == "uebernommen" \
                and [p["id"] for p in r.json["recherche"]["produkte"]] == [pid1], r.json["recherche"]
            os.rename(pfad + ".beiseite", pfad)
            # Ein zweiter Klick hängt nur an, was fehlt – nichts doppelt, kein zweiter Journaleintrag.
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json=anfrage, headers=H)
            an = r.json["anhaengen"]
            assert an == {"angehaengt": 1, "uebersprungen": 2, "fehler": []}, an
            assert kat.post(f"{BASIS}/{lid}/anhaengen", json=anfrage, headers=H).json["anhaengen"]["angehaengt"] == 0
            with app.app_context():
                arten = [x["kind"] for x in db.query("SELECT kind FROM mat_product_document WHERE product_id = ? "
                                                     "ORDER BY kind", (pid1,))]
                assert arten == ["gebrauchsanleitung", "konformitaetserklaerung"], arten
                assert db.query("SELECT image FROM mat_product WHERE id = ?", (pid1,), one=True)["image"]
                ue = json.loads(ki.zeile(lid)["ergebnis_json"])["uebernahme"]
                assert [(e["nr"], e["product_id"], e["dateien"], bool(e["bild"])) for e in ue["produkte"]] \
                    == [(1, pid1, sorted([anl, erkl]), True)] and ue["produkte"][0]["am"], ue
                eintraege = db.query("SELECT * FROM mat_audit WHERE entity = 'ki_lauf' AND entity_id = ? ORDER BY id",
                                     (lid,))
                assert [e["action"] for e in eintraege] == ["recherche_gestartet", "recherche_beendet",
                                                            "recherche_uebernommen"], [e["action"] for e in eintraege]
                nachher = json.loads(eintraege[-1]["after_json"])
                assert nachher["produkte"] == [pid1] and nachher["ausfuehrung"] == 1 and nachher["ki_lauf"] == lid \
                    and nachher["felder"] == ["article_no", "manufacturer", "model", "norm"] \
                    and len(nachher["dateien"]) == 3 and any(x.startswith("Produktbild") for x in nachher["dateien"]), \
                    nachher
            # Journal am Produkt: die Einträge des Laufs nur für die Material-Verwaltung.
            j = kat.get(f"/api/material/produkte/{pid1}").json["produkt"]["journal"]
            assert {e["action"] for e in j if e["entity"] == "ki_lauf"} == {"recherche_gestartet", "recherche_beendet",
                                                                           "recherche_uebernommen"}, j
            j = k["fuehrung"].get(f"/api/material/produkte/{pid1}").json["produkt"]["journal"]
            assert not [e for e in j if e["entity"] == "ki_lauf"], j
            # Der Vorschlag bleibt im Reiter (PR-2 ist noch anlegbar); PR-1 steht jetzt „im Katalog“.
            st = kat.get(BASIS).json["recherche"]
            assert st["status"] == "uebernommen" \
                and [a["anlegbar"] for a in st["vorschlag"]["ausfuehrungen"]] == [False, True, False] \
                and st["vorschlag"]["ausfuehrungen"][0]["im_katalog"]["id"] == pid1, st
            # Eine zweite Ausführung später; danach ist keine mehr anlegbar – der Reiter zeigt den Start.
            pid2 = produkt_anlegen(kat, ids, "PR-2")
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": pid2, "nr": 2, "dateien": [blatt]}, headers=H)
            assert r.status_code == 200 and r.json["anhaengen"]["angehaengt"] == 1, r.get_json()
            assert [p["id"] for p in r.json["recherche"]["produkte"]] == [pid1, pid2]
            assert kat.get(BASIS).json["recherche"] is None
            with app.app_context():
                assert db.query("SELECT COUNT(*) AS n FROM mat_audit WHERE entity = 'ki_lauf' AND entity_id = ? AND "
                                "action = 'recherche_uebernommen'", (lid,), one=True)["n"] == 2
            # Ohne Dateien geht es auch (der Lauf gilt dann als übernommen) – hier ein schon übernommenes Produkt.
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": pid2, "nr": 2}, headers=H)
            assert r.status_code == 200 and r.json["anhaengen"]["fehler"] == [], r.get_json()
            # O1: PR-2 gelöscht, ein neues Produkt bekommt dieselbe Kennung – der alte Eintrag gilt nicht mehr, das neue
            # bekommt einen eigenen; die Statuszeile nennt nur das neue.
            with app.app_context():
                assert pid2 == db.query("SELECT MAX(id) AS n FROM mat_product", one=True)["n"]
                # Die Übernahme von PR-2 liegt „früher“ (sonst fiele alles in dieselbe Sekunde).
                erg = json.loads(ki.zeile(lid)["ergebnis_json"])
                erg["uebernahme"]["produkte"][1]["am"] = "2000-01-01T00:00:00+00:00"
                db.execute("UPDATE ki_laeufe SET ergebnis_json = ? WHERE id = ?", (json.dumps(erg), lid))
            assert kat.delete(f"/api/material/produkte/{pid2}", headers=H).status_code == 200
            st = kat.get(f"{BASIS}/{lid}").json["recherche"]
            assert [p["id"] for p in st["produkte"]] == [pid1], st["produkte"]
            neu = produkt_anlegen(kat, ids, "PR-2", model="Rettungsgurt Probe", description="neu")
            assert neu == pid2
            st = kat.get(f"{BASIS}/{lid}").json["recherche"]
            assert [p["id"] for p in st["produkte"]] == [pid1], st["produkte"]      # das neue ist ein anderes
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": neu, "nr": 2, "dateien": [blatt]}, headers=H)
            assert r.status_code == 200 and r.json["anhaengen"]["angehaengt"] == 1, r.get_json()
            assert [p["id"] for p in r.json["recherche"]["produkte"]] == [pid1, neu]
            with app.app_context():
                ue = json.loads(ki.zeile(lid)["ergebnis_json"])["uebernahme"]
                assert [e["product_id"] for e in ue["produkte"]] == [pid1, neu] \
                    and ue["produkte"][1]["am"] > "2000-01-01", ue
        finally:
            mails_zurueck(alt_mail)
            netz_zurueck(alt_netz)
            server.stop()
    print("Anhängen ohne Meldung bestanden.")


def test_anhaengen_aus_meldung():
    """Aus „Produkt aus Meldung anlegen“: derselbe Lauf wie an der Karte; anhaengen nur, wenn die Meldung mit genau
    diesem Produkt erledigt ist (409 sonst); danach „übernommen“ mit dem Produkt, Journal unter entity „recherche“."""
    from app import db, ki
    from app.material.services import meldung
    with tempfile.TemporaryDirectory() as tmp:
        server, alt_netz, app, k, ids, gid = _umgebung(tmp)
        post = []
        alt_mail = mails_abfangen(meldung, lambda an, betreff, inhalt: post.append((an, betreff)) or True)
        kat = k["katalog"]
        try:
            mid = melden(k, gid)
            alt = einsetzen(Attrappe(antworter(server, ids["gurte"], {"geprueft": []})))
            try:
                assert kat.post(f"/api/material/meldungen/{mid}/recherche", json={"domains": ["hersteller.test"]},
                                headers=H).status_code == 202
                z = warten(mid, app)
            finally:
                ki.CLIENT = alt
            lid = z["id"]
            v = kat.get(f"/api/material/meldungen/{mid}/recherche").json["recherche"]["vorschlag"]
            d = dateien_nach_name(v)
            anl = d["anleitung.pdf"]["n"]
            # Der eigene Lauf ohne Meldung ist es nicht.
            assert kat.get(BASIS).json["recherche"] is None
            # Vor dem Anlegen (Meldung offen): 409.
            fremd = produkt_anlegen(kat, ids, "PR-77")
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": fremd, "nr": 1, "dateien": [anl]}, headers=H)
            assert r.status_code == 409 and "Meldung" in r.json["error"], r.get_json()
            # „Anlegen“ wie heute über die Meldung (legt an, erledigt, Mail an den Melder).
            r = kat.post(f"/api/material/meldungen/{mid}/produkt", headers=H, json={
                "category_id": ids["gurte"], "manufacturer": "Hersteller", "model": "Rettungsgurt Probe",
                "article_no": "PR-1", "material_kind": "textil", "lifetime_years": 10, "antwort": ""})
            assert r.status_code == 201, r.get_json()
            pid = r.json["produkt"]["id"]
            assert any("wart@example.org" in str(an) for an, _ in post), post      # Bescheid an den Melder
            with app.app_context():
                assert ki.zeile(lid)["status"] == "fertig"     # bleibt fertig, bis anhaengen kommt
            # Ein anderes Produkt als das der Meldung: 409.
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": fremd, "nr": 1}, headers=H)
            assert r.status_code == 409, r.get_json()
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": pid, "nr": 1, "dateien": [anl], "bild": True,
                                                         "felder": ["norm"]}, headers=H)
            assert r.status_code == 200 and r.json["anhaengen"]["angehaengt"] == 2, r.get_json()
            assert r.json["recherche"]["status"] == "uebernommen" and [p["id"] for p in r.json["recherche"]["produkte"]] \
                == [pid]
            # Die Karte zeigt „Aus der Recherche … angelegt: <Produkt>“ (recherche.produkte in der Liste).
            liste = kat.get("/api/material/meldungen?status=erledigt").json["meldungen"]
            m = next(x for x in liste if x["id"] == mid)
            assert m["recherche"]["status"] == "uebernommen" and [p["id"] for p in m["recherche"]["produkte"]] == [pid]
            with app.app_context():
                e = db.query("SELECT * FROM mat_audit WHERE entity = 'recherche' AND entity_id = ? AND action = "
                             "'recherche_uebernommen'", (mid,))
                assert len(e) == 1 and json.loads(e[0]["after_json"])["produkte"] == [pid], [dict(x) for x in e]
                assert not db.query("SELECT 1 FROM mat_audit WHERE entity = 'ki_lauf'", one=True)
                ue = json.loads(ki.zeile(lid)["ergebnis_json"])["uebernahme"]
                assert ue["haupt"] == pid and ue["produkte"][0]["product_id"] == pid
            # Nachladen an der Meldung geht danach wie immer.
            r = kat.post(f"/api/material/meldungen/{mid}/recherche/nachladen", headers=H)
            assert r.status_code == 200 and r.json["anhaengen"]["angehaengt"] == 0, r.get_json()
        finally:
            mails_zurueck(alt_mail)
            netz_zurueck(alt_netz)
            server.stop()
    print("Anhängen aus einer Meldung bestanden.")


# --- Aufräumen, Kontolöschung, tote Läufe ---------------------------------------------------------------------------

def test_aufraeumen_konto_tote():
    """Läufe ohne Meldung behalten ihre Dateien bis zur Frist (30 Tage nach dem Ende); vorher weg bei einem neueren
    eigenen Lauf, bei „verworfen“ und ohne Konto. Meldungsläufe wie bisher. Kontolöschung leert die eigenen Läufe ohne
    Meldung; ein toter Lauf ohne Meldung trägt „Recherche beendet“ (entity „ki_lauf“). JOURNAL_BLEIBT kennt „ki_lauf“."""
    from app import db, ki
    from app.material.services import bestand_leeren, recherche
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ANTHROPIC_API_KEY"] = SCHLUESSEL
        app, k = umgebung(os.path.join(tmp, "daten"))
        _, uid2 = neues_konto(app, "katalog2@example.org", "lesen", rechte={"material": 3})
        with app.app_context():
            uid1 = db.query("SELECT id FROM users WHERE email = 'katalog@example.org'", one=True)["id"]
            alt = "2020-01-01T00:00:00+00:00"
            jetzt = db.now()

            def lauf(uid, beendet=jetzt, status="fertig", bezug="mat_katalog", erg=None):
                lid = db.execute(
                    "INSERT INTO ki_laeufe (art, bezug, status, eingabe_json, ergebnis_json, gestartet_von, "
                    "gestartet_von_name, gestartet_am, beendet_am) VALUES ('mat_recherche', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (bezug, status, json.dumps({"meldung": {"hersteller": "H", "modell": "M"}}),
                     json.dumps(erg or {"vorschlag": {"ausfuehrungen": [], "dateien": []}}), uid, "Probe",
                     beendet, beendet))
                os.makedirs(ki.ordner(lid), exist_ok=True)
                return lid
            frisch = lauf(uid1)
            abgelaufen = lauf(uid2, beendet=alt)
            verworfen = lauf(uid2, erg={"verworfen": jetzt})
            ersetzt = lauf(uid1)
            neuer = lauf(uid1)              # ersetzt „frisch“ und „ersetzt“
            ohne_konto = lauf(None)
            meldungslauf = lauf(uid1, bezug="mat_meldung:4242")       # Meldung gibt es nicht → weg wie bisher
            recherche.aufraeumen()
            da = {n: os.path.isdir(ki.ordner(n)) for n in (frisch, abgelaufen, verworfen, ersetzt, neuer,
                                                           ohne_konto, meldungslauf)}
            assert da == {frisch: False, abgelaufen: False, verworfen: False, ersetzt: False, neuer: True,
                          ohne_konto: False, meldungslauf: False}, da
            eigen2 = lauf(uid2)
            assert os.path.isdir(ki.ordner(eigen2))
            recherche.aufraeumen()
            assert os.path.isdir(ki.ordner(eigen2)) and os.path.isdir(ki.ordner(neuer))
            # Ein Meldungslauf mit einer Meldung, die es gibt und die offen ist, bleibt.
            mid = db.execute("INSERT INTO mat_product_request (manufacturer, model, article_no, dedupe_key, "
                             "links_json, photos_json, created_at) VALUES ('H', 'M', '', 'h|m|', '[]', '[]', ?)",
                             (jetzt,))
            offen = lauf(uid1, bezug=f"mat_meldung:{mid}")
            recherche.aufraeumen()
            assert os.path.isdir(ki.ordner(offen))
            # Die Meldungsliste stört eine Zeile mit bezug „mat_katalog“ nicht.
            assert recherche.je_meldung([mid])[mid]["id"] == offen
        r = k["katalog"].get("/api/material/meldungen")
        assert r.status_code == 200 and [m["recherche"]["id"] for m in r.json["meldungen"]] == [offen], r.json
        # Kontolöschung: die eigenen Läufe ohne Meldung verlieren Inhalt und Dateien, Meldungsläufe nur den Namen.
        assert k["adm"].delete(f"/api/admin/users/{uid2}", headers=H).status_code == 200
        with app.app_context():
            z = ki.zeile(eigen2)
            assert z["eingabe_json"] == "{}" and z["ergebnis_json"] is None and z["gestartet_von"] is None \
                and z["gestartet_von_name"] == ki.GELOESCHT and not os.path.isdir(ki.ordner(eigen2)), dict(z)
            assert ki.zeile(offen)["eingabe_json"] != "{}"
            # Ein toter Lauf ohne Meldung: „Recherche beendet“ unter entity „ki_lauf“ im Namen dessen, der startete.
            tot = db.execute("INSERT INTO ki_laeufe (art, bezug, status, eingabe_json, gestartet_von, "
                             "gestartet_von_name, gestartet_am, lebenszeichen_am) VALUES ('mat_recherche', "
                             "'mat_katalog', 'laeuft', '{}', ?, 'Katalog Probe', ?, ?)", (uid1, alt, alt))
            assert tot in ki.tote_aufraeumen()
            e = db.query("SELECT * FROM mat_audit WHERE entity = 'ki_lauf' AND entity_id = ?", (tot,))
            assert [x["action"] for x in e] == ["recherche_beendet"] and e[0]["user_name"] == "Katalog Probe" \
                and json.loads(e[0]["after_json"])["grund"] == ki.TOT_TEXT, [dict(x) for x in e]
        assert "ki_lauf" in bestand_leeren.JOURNAL_BLEIBT
    print("Aufräumen, Kontolöschung und tote Läufe bestanden.")


# --- Rechte je Rolle ------------------------------------------------------------------------------------------------

def test_rechte():
    """Alle sieben neuen Routen: Plattform- und Material-Verwaltung dürfen, Materialwart, Führungskraft, Prüfer ohne
    Freigabe und ein Konto ohne Modulzugang bekommen 403, ohne Anmeldung 401. darf.recherche nur für die
    Material-Verwaltung mit Schlüssel, nicht in der Übung."""
    from app import einfuehrung, ki
    from app.material.services import meldung
    with tempfile.TemporaryDirectory() as tmp:
        server, alt_netz, app, k, ids, gid = _umgebung(tmp)
        alt_mail = mails_abfangen(meldung)
        try:
            z, _ = recherchieren(k["adm"], app, Attrappe(antworter(server, ids["gurte"], {"geprueft": []})),
                                 formular(ids["gurte"]))
            lid = z["id"]
            pid = produkt_anlegen(k["adm"], ids, "PR-1")
            wege = [("get", BASIS, None), ("post", BASIS, formular(ids["gurte"], article_no="PR-3")),
                    ("get", f"{BASIS}/{lid}", None), ("post", f"{BASIS}/{lid}/abbrechen", None),
                    ("get", f"{BASIS}/{lid}/dateien/1", None),
                    ("post", f"{BASIS}/{lid}/anhaengen", {"product_id": pid, "nr": 1}),
                    ("post", f"{BASIS}/{lid}/verwerfen", None)]

            def aufruf(c, art, weg, d):
                return getattr(c, art)(weg, json=d, headers=H) if art == "post" else c.get(weg)
            for wer in ("wart", "fuehrung", "pruefer", "nutzer"):
                for art, weg, d in wege:
                    r = aufruf(k[wer], art, weg, d)
                    assert r.status_code == 403, (wer, weg, r.status_code)
            for art, weg, d in wege:
                assert aufruf(app.test_client(), art, weg, d).status_code == 401, weg
            # Material-Verwaltung (fremder Lauf: lesen ja, verwerfen 403) und Plattform-Verwaltung (eigener).
            kat = k["katalog"]
            assert kat.get(BASIS).status_code == 200 and kat.get(f"{BASIS}/{lid}").status_code == 200
            assert kat.get(f"{BASIS}/{lid}/dateien/1").status_code == 200
            assert kat.post(f"{BASIS}/{lid}/abbrechen", headers=H).status_code == 409          # läuft nicht mehr
            assert kat.post(f"{BASIS}/{lid}/verwerfen", headers=H).status_code == 403
            r = kat.post(f"{BASIS}/{lid}/anhaengen", json={"product_id": pid, "nr": 1}, headers=H)
            assert r.status_code == 200, r.get_json()
            assert k["adm"].get(BASIS).json["recherche"]["id"] == lid
            assert k["adm"].post(f"{BASIS}/{lid}/verwerfen", headers=H).status_code == 200
            alt = einsetzen(Attrappe(antworter(server, ids["gurte"], {"geprueft": []})))
            try:
                r = kat.post(BASIS, json=formular(ids["gurte"], article_no="PR-3"), headers=H)
                assert r.status_code == 202, r.get_json()
                lauf_ende(app, r.json["recherche"]["id"])
            finally:
                ki.CLIENT = alt
            # darf.recherche: Material-Verwaltung mit Schlüssel – sonst nicht; in der Übung fehlt das Feld.
            assert kat.get("/api/material/start").json["darf"]["recherche"] is True
            assert k["adm"].get("/api/material/start").json["darf"]["recherche"] is True
            for wer in ("wart", "fuehrung", "pruefer"):
                assert k[wer].get("/api/material/start").json["darf"]["recherche"] is False, wer
            html = kat.get("/materialablage/katalog").get_data(as_text=True)
            darf = json.loads(re.search(r'data-darf="([^"]*)"', html).group(1).replace("&#34;", '"'))
            assert darf["recherche"] is True and darf["katalog"] is True, darf
            os.environ.pop("ANTHROPIC_API_KEY")
            try:
                assert kat.get("/api/material/start").json["darf"]["recherche"] is False
                # Ohne Schlüssel bleibt Lesen, Start und Abbrechen antworten 503.
                assert kat.get(BASIS).status_code == 200
                assert kat.post(BASIS, json=formular(), headers=H).status_code == 503
                assert kat.post(f"{BASIS}/{lid}/abbrechen", headers=H).status_code == 503
            finally:
                os.environ["ANTHROPIC_API_KEY"] = SCHLUESSEL
            assert all("recherche" not in d for d in einfuehrung.DARF_MATERIAL.values())
            html = kat.get("/materialablage/katalog?uebung=verwaltung").get_data(as_text=True)
            m = re.search(r'data-darf="([^"]*)"', html)
            if m:
                darf = json.loads(m.group(1).replace("&#34;", '"'))
                assert "recherche" not in darf, darf
        finally:
            mails_zurueck(alt_mail)
            netz_zurueck(alt_netz)
            server.stop()
    print("Rechte der Recherche im Produktdialog bestanden.")


if __name__ == "__main__":
    test_start_ohne_meldung()
    test_eigener_lauf_und_verwerfen()
    test_anhaengen_ohne_meldung()
    test_anhaengen_aus_meldung()
    test_aufraeumen_konto_tote()
    test_rechte()

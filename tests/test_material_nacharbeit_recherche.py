"""Wunsch des Nutzers vom 26.11.2026: „Füge die KI-Recherche noch bei der Nacharbeit von Importen als Material-Verwaltung
ein, bei ‚In Katalog aufnehmen‘“.
python tests/test_material_nacharbeit_recherche.py  oder  pytest tests/test_material_nacharbeit_recherche.py

Bisher hatte der Dialog „Im Katalog anlegen“ der Nacharbeit keine Reiter (Entscheidung A2 A vom 22.11.2026). Jetzt
bekommt er Variante A2 B des Entwurfs entwurf_recherche_reiter_produkt.md: die Reiter „Produkt“ und „Recherche“, ohne
„Bestandteile“ – nur für die Material-Verwaltung mit API-Schlüssel. Nach „Anlegen“ hängen die gewählten Dateien aus der
Recherche am neuen Produkt, und die Nacharbeit ordnet es wie bisher der Angabe zu. Geprüft in der echten App (Server im
Faden) in Chromium. Statt der Claude API antwortet die Attrappe aus test_ki.py, Dateien kommen vom lokalen HTTPS-Server aus
test_material_recherche.py. Es gibt keine echten API-Aufrufe und keine Downloads aus dem Netz. Ohne Schlüssel bleibt der
Dialog ohne Reiter wie bisher. Ohne Chromium übersprungen. Alle Namen und Nummern sind Platzhalter."""
import os
import sys
import tempfile

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)
sys.path.insert(0, os.path.join(WURZEL, "tests"))

from einfuehrung_browser import Umgebung, uebersprungen  # noqa: E402

REITER = "[...document.querySelectorAll('dialog[open] [role=tab]')].map((t) => t.dataset.reiter)"


def _fehler(s):
    return [f for f in s.b.fehler() if "favicon" not in f]


def _angebot_weg(s):
    """Das Angebot der Einführung (Karte unten rechts) liegt sonst über Knöpfen der Seite."""
    s.js("[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Nicht jetzt')?.click()")


def _aufbau(u):
    from test_material import katalog_grund
    from test_material_import import csv_bytes, ok, uebernehmen
    from test_material_ueberblick import ordner_neu
    ids = katalog_grund(u.adm)
    r = u.adm.post("/api/material/ordner", json={"name": "OG Platzhalter", "kind": "gliederung"})
    assert r.status_code == 201, r.get_json()
    lager = ordner_neu(u.adm, r.json["ordner"]["id"], "Lager Platzhalter")
    ok(uebernehmen(u.adm, lager, csv_bytes([["Hersteller", "Modell", "Artikelnummer", "Seriennummer"],
                                            ["Hersteller", "Rettungsgurt Probe", "PR-1", "NR-0001"]])), 201)
    zeile = u.sql("SELECT r.id FROM mat_import_row r JOIN mat_import i ON i.id = r.import_id "
                  "WHERE i.folder_id = ? AND r.status = 'offen'", (lager,))
    assert len(zeile) == 1, zeile
    return ids, lager, zeile[0]["id"]


def _dialog_oeffnen(s, lager):
    s.oeffnen(f"/materialablage/ordner/{lager}/import", warten=1.0)
    assert s.warte("!!document.querySelector('[data-act=\"na-anlegen\"]')", sek=15), "Knopf „Im Katalog anlegen“"
    _angebot_weg(s)
    s.ruhe(1.0)
    assert s.klick('[data-act="na-anlegen"]') is None
    assert s.warte("!!document.querySelector('dialog[open] #pd-ok')", sek=10), "Produktdialog"
    # Vorbelegt aus der Angabe der Nacharbeit
    assert s.js("['pd-her', 'pd-mod', 'pd-art'].map((i) => document.getElementById(i).value)") \
        == ["Hersteller", "Rettungsgurt Probe", "PR-1"]


def _mit_schluessel(u, server):
    from test_ki import Attrappe, einsetzen
    from test_material_recherche import antworter
    ids, lager, zeile = _aufbau(u)
    s = u.seite("matverwaltung", 1280, 900)
    try:
        _dialog_oeffnen(s, lager)
        # Reiter „Produkt“ und „Recherche“, kein „Bestandteile“; Start im Reiter „Produkt“
        assert s.js(REITER) == ["produkt", "recherche"], s.js(REITER)
        assert s.js("!document.getElementById('pd-teil-bestandteile') && !document.getElementById('pd-teil-produkt').hidden")
        assert s.js("document.querySelector('dialog[open] h2').textContent") == "Produkt anlegen"
        alt = einsetzen(Attrappe(antworter(server, ids["gurte"], {"geprueft": []})))
        try:
            assert s.klick("#pd-reiter-recherche") is None
            assert s.warte("!!document.getElementById('pd-rs-domains')", sek=10), "Startteil der Recherche"
            s.js("(() => { const f = document.getElementById('pd-rs-domains'); f.value = 'hersteller.test';"
                 " f.dispatchEvent(new Event('input', { bubbles: true })); })()")
            assert s.klick("#pd-rs-los") is None
            # Der Reiter fragt alle 5 s nach; die Attrappe ist schnell fertig.
            assert s.warte("!!document.getElementById('pd-rs-uebernehmen')", sek=45), \
                s.js("document.getElementById('pd-teil-recherche').innerText")
        finally:
            einsetzen(alt)
        assert s.js("document.querySelector('input[name=\"pd-rs-nr\"]:checked')?.value") == "1" \
            or s.klick('input[name="pd-rs-nr"][value="1"]') is None
        assert s.klick("#pd-rs-uebernehmen") is None
        # Zurück im Reiter „Produkt“: Kategorie aus dem Vorschlag, darunter die Dateien aus der Recherche
        assert s.warte("!document.getElementById('pd-teil-produkt').hidden && document.querySelectorAll('.pd-rs-datei').length > 0",
                       sek=10), "Dateien aus der Recherche"
        assert s.js("document.getElementById('pd-kat').value") == str(ids["gurte"])
        gewaehlt = s.js("document.querySelectorAll('.pd-rs-datei:checked').length")
        assert gewaehlt >= 1, gewaehlt
        assert s.klick("#pd-ok") is None
        # Nach dem Anlegen: Zuordnung in der Nacharbeit, danach gleich die Prüfung „Zugeordnet – übernehmen?“
        assert s.warte("!!document.querySelector('dialog[open]') && document.querySelector('dialog[open] h2')"
                       "?.textContent.startsWith('Zugeordnet')", sek=20), s.js("document.querySelector('dialog[open] h2')?.textContent")
        assert not _fehler(s), _fehler(s)
    finally:
        s.schliessen()
    # Der Vorschlag überschreibt Hersteller und Modell mit seinen Werten (die Attrappe schreibt „hersteller“ klein).
    produkt = u.sql("SELECT id, category_id, image FROM mat_product WHERE manufacturer = 'hersteller' COLLATE NOCASE "
                    "AND model = 'Rettungsgurt Probe' COLLATE NOCASE")
    assert len(produkt) == 1 and produkt[0]["category_id"] == ids["gurte"], produkt
    pid = produkt[0]["id"]
    doks = u.sql("SELECT kind FROM mat_product_document WHERE product_id = ?", (pid,))
    assert len(doks) == gewaehlt, (doks, gewaehlt)
    assert u.sql("SELECT product_id FROM mat_import_row WHERE id = ?", (zeile,))[0]["product_id"] == pid
    lauf = u.sql("SELECT status, bezug FROM ki_laeufe ORDER BY id DESC LIMIT 1")
    assert lauf and lauf[0]["status"] == "uebernommen", lauf


def _ohne_schluessel(u):
    _, lager, _ = _aufbau(u)
    s = u.seite("matverwaltung", 1280, 900)
    try:
        _dialog_oeffnen(s, lager)
        assert s.js(REITER) == [] and not s.js("!!document.getElementById('pd-teil-recherche')")
        assert not _fehler(s), _fehler(s)
    finally:
        s.schliessen()


def test_nacharbeit_mit_recherche():
    if uebersprungen():
        print("übersprungen – kein Chromium")
        return
    from test_ki import SCHLUESSEL
    from test_material_recherche import netz_einsetzen, netz_server, netz_zurueck
    alt_schluessel = os.environ.get("ANTHROPIC_API_KEY")
    with tempfile.TemporaryDirectory() as tmp:
        server, _ = netz_server(tmp)
        alt_netz = netz_einsetzen(server)
        try:
            os.environ["ANTHROPIC_API_KEY"] = SCHLUESSEL
            os.environ.pop("MATERIAL_RECHERCHE_JE_MONAT", None)
            with Umgebung() as u:
                _mit_schluessel(u, server)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with Umgebung() as u:
                _ohne_schluessel(u)
        finally:
            netz_zurueck(alt_netz)
            server.stop()
            if alt_schluessel is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = alt_schluessel


if __name__ == "__main__":
    test_nacharbeit_mit_recherche()
    print("ok")

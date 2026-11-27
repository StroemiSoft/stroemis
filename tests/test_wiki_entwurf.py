"""Wunsch des Nutzers zur Strömipedia vom 26.11.2026: „Alle Artikel in der Strömipedia, die nicht veröffentlicht sind, sollen
als Entwurf gekennzeichnet werden“.
python tests/test_wiki_entwurf.py  oder  pytest tests/test_wiki_entwurf.py

Veröffentlicht heißt für alle Angemeldeten freigegeben, entweder die Seite selbst oder ein Abschnitt darüber samt
Unterseiten (api_wiki.is_public). Alle anderen Seiten sind Entwürfe. Entschieden hat der Nutzer „Titel + Baum grau“ und
„Vorlagen ausnehmen“: Am Seitentitel steht die graue Marke „Entwurf“. Im Seitenbaum ist der Titel grau, das Wort steht im
Tooltip und für Vorlesehilfen. Lesebeschränkte Seiten zählen als Entwurf, Vorlagen nicht. Geprüft in der echten App
(Server im Faden) in Chromium für die Wiki-Verwaltung und ein Mitglied, dazu einmal Freigeben über „Teilen“: Danach
verschwindet die Marke sofort. Nachtrag vom 27.11.2026 („Bei Artikeln, die über ihren Überartikel freigegeben sind, soll
das auch durch ein Symbol indiziert werden, das sich aber leicht unterscheidet“): Solche Seiten tragen im Baum den Globus
grau und blasser (Klasse „pub geerbt“), Tooltip und Vorlesehilfe nennen den nächsten freigegebenen Abschnitt darüber. Ohne
Chromium übersprungen."""
import os
import sys

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)
sys.path.insert(0, os.path.join(WURZEL, "tests"))

from einfuehrung_browser import Umgebung, uebersprungen  # noqa: E402

# Je Baumzeile: Ist der Titel grau, steht „ – Entwurf“ im Tooltip und „ (Entwurf)“ für Vorlesehilfen?
BAUM = r"""(() => Object.fromEntries([...document.querySelectorAll('#tree li[data-id]')].map((li) => {
  const a = li.querySelector(':scope > .row > a'), t = a.querySelector('.baum-titel');
  return [li.dataset.id, { grau: t.classList.contains('entwurf'), tooltip: a.title, vorlesen: (t.querySelector(':scope > .nur-vorlesen') || {}).textContent || '',
                           farbe: getComputedStyle(t).color,
                           globus: [...t.querySelectorAll('.pub')].map((g) => ({ geerbt: g.classList.contains('geerbt'), tooltip: g.title,
                             vorlesen: (g.querySelector('.nur-vorlesen') || {}).textContent || '',
                             filter: getComputedStyle(g).filter, deckkraft: getComputedStyle(g).opacity })) }]; })))()"""
KOPF = r"""(() => { const h = document.querySelector('h1.seitentitel'); if (!h) return null;
  const e = h.querySelector('.entwurfbadge');
  return { entwurf: e ? e.textContent : null, klassen: e ? e.className : '', frei: !!h.querySelector('.pubbadge'),
           hinweis: e ? e.title : '' }; })()"""
GRAU = "rgb(109, 109, 108)"     # --grau


def _seite(u, titel, eltern=None):
    r = u.adm.post("/api/wiki/pages", json={"title": titel, "content": f"Text zu {titel}.", "parent_id": eltern})
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json().get("page") or r.get_json()


def _ok(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _fehler(s):
    return [f for f in s.b.fehler() if "favicon" not in f]


def _aufbau(u):
    s = {}
    s["einzeln"] = _seite(u, "Einzeln freigegeben")
    s["unter_einzeln"] = _seite(u, "Unter der Einzelfreigabe", s["einzeln"]["id"])
    s["abschnitt"] = _seite(u, "Freigegebener Abschnitt")
    s["im_abschnitt"] = _seite(u, "Im Abschnitt", s["abschnitt"]["id"])
    s["tiefer"] = _seite(u, "Tiefer im Abschnitt", s["im_abschnitt"]["id"])
    s["innen"] = _seite(u, "Innerer Abschnitt", s["abschnitt"]["id"])
    s["im_innen"] = _seite(u, "Im inneren Abschnitt", s["innen"]["id"])
    s["entwurf"] = _seite(u, "Noch ein Entwurf")
    s["geheim"] = _seite(u, "Beschränkt")
    s["vorlage"] = _seite(u, "Vorlage Bericht")
    _ok(u.adm.put(f"/api/wiki/pages/{s['einzeln']['id']}/share", json={"is_public": True, "public_children": False}))
    _ok(u.adm.put(f"/api/wiki/pages/{s['abschnitt']['id']}/share", json={"is_public": True, "public_children": True}))
    _ok(u.adm.put(f"/api/wiki/pages/{s['innen']['id']}/share", json={"is_public": True, "public_children": True}))
    _ok(u.adm.put(f"/api/wiki/pages/{s['geheim']['id']}/restrict", json={"read_restricted": True}))
    _ok(u.adm.put(f"/api/wiki/pages/{s['vorlage']['id']}/options", json={"is_template": True}))
    return s


def _globus_pruefen(name, z, globus):
    """globus: None (keiner), "eigen" (eigene Freigabe) oder der Titel des Abschnitts, über den die Seite freigegeben ist."""
    if globus is None:
        assert z["globus"] == [], (name, z)
    elif globus == "eigen":
        assert z["globus"] == [{"geerbt": False, "tooltip": "für alle Angemeldeten freigegeben", "vorlesen": "",
                                "filter": "none", "deckkraft": "1"}], (name, z)
    else:
        assert z["globus"] == [{"geerbt": True, "tooltip": f"über „{globus}“ für alle Angemeldeten freigegeben",
                                "vorlesen": f" (über „{globus}“ freigegeben)", "filter": "grayscale(1)",
                                "deckkraft": "0.6"}], (name, z)


def _pruefen(s, seiten, entwuerfe, frei, globen):
    """Baum und Kopf jeder Seite: grau und mit Marke genau die Entwürfe, „für alle Angemeldeten“ genau die freigegebenen;
    der Globus im Baum je nach eigener oder geerbter Freigabe."""
    baum = s.js(BAUM)
    for name, p in seiten.items():
        z = baum[str(p["id"])]
        _globus_pruefen(name, z, globen.get(name))
        if name in entwuerfe:
            assert z["grau"] and z["farbe"] == GRAU, (name, z)
            assert z["tooltip"] == f"{p['title']} – Entwurf" and z["vorlesen"] == " (Entwurf)", (name, z)
        else:
            assert not z["grau"] and z["farbe"] != GRAU and z["tooltip"] == p["title"] and not z["vorlesen"], (name, z)
    for name, p in seiten.items():
        s.oeffnen(f"/stroemipedia/{p['slug']}", warten=0.5)
        assert s.warte(f"document.querySelector('h1.seitentitel')?.textContent.startsWith({p['title']!r})", sek=10), name
        kopf = s.js(KOPF)
        if name in entwuerfe:
            assert kopf["entwurf"] == "Entwurf" and "badge grey" in kopf["klassen"] and not kopf["frei"], (name, kopf)
            assert kopf["hinweis"] == "Noch nicht veröffentlicht – nicht für alle Angemeldeten freigegeben", kopf
        else:
            assert kopf["entwurf"] is None and kopf["frei"] == (name in frei), (name, kopf)
        # Die geöffnete Seite bleibt im Baum grau (a.active setzt nur Kante und Gewicht).
        z = s.js(BAUM)[str(p["id"])]
        assert z["grau"] == (name in entwuerfe) and (z["farbe"] == GRAU) == (name in entwuerfe), (name, z)


def _lauf(u):
    seiten = _aufbau(u)
    frei = {"einzeln", "abschnitt", "im_abschnitt", "tiefer", "innen", "im_innen"}
    entwuerfe = {"unter_einzeln", "entwurf", "geheim"}
    # Eigene Freigabe: voller Globus. Darunter der abgeschwächte mit dem nächsten freigegebenen Abschnitt – unter „Innerer
    # Abschnitt“ (selbst samt Unterseiten freigegeben) also dieser, nicht der äußere.
    globen = {"einzeln": "eigen", "abschnitt": "eigen", "im_abschnitt": "Freigegebener Abschnitt",
              "tiefer": "Freigegebener Abschnitt", "innen": "eigen", "im_innen": "Innerer Abschnitt"}
    # Die Wiki-Verwaltung sieht auch die beschränkte Seite; ein Mitglied sieht sie nicht.
    for rolle, sichtbar in (("wikiverwaltung", seiten), ("mitglied", {k: v for k, v in seiten.items() if k != "geheim"})):
        s = u.seite(rolle, 1280, 900)
        try:
            s.oeffnen(f"/stroemipedia/{seiten['entwurf']['slug']}", warten=1.0)
            assert s.warte(f"!!document.querySelector('#tree li[data-id=\"{seiten['tiefer']['id']}\"]')", sek=10), rolle
            baum = s.js(BAUM)
            assert (str(seiten["geheim"]["id"]) in baum) == (rolle == "wikiverwaltung"), (rolle, sorted(baum))
            _pruefen(s, sichtbar, entwuerfe, frei, globen)
            assert not _fehler(s), (rolle, _fehler(s))
        finally:
            s.schliessen()

    # Freigeben über „Teilen“: Kopf und Baum ziehen ohne Neuladen nach, die Unterseite der Einzelfreigabe bleibt Entwurf.
    s = u.seite("wikiverwaltung", 1280, 900)
    try:
        p = seiten["entwurf"]
        s.oeffnen(f"/stroemipedia/{p['slug']}", warten=1.0)
        assert s.warte("!!document.querySelector('h1.seitentitel .entwurfbadge')", sek=10)
        assert s.klick("#pg-share") is None
        assert s.warte("!!document.querySelector('dialog[open] #sh-public')", sek=10)
        assert s.klick("dialog[open] #sh-public") is None
        assert s.klick("dialog[open] #sh-save") is None
        assert s.warte("!document.querySelector('dialog[open]') && !!document.querySelector('h1.seitentitel .pubbadge')", sek=10)
        assert s.js(KOPF)["entwurf"] is None
        z = s.js(BAUM)
        assert not z[str(p["id"])]["grau"] and z[str(seiten["unter_einzeln"]["id"])]["grau"], z
        _globus_pruefen("entwurf", z[str(p["id"])], "eigen")
        _globus_pruefen("unter_einzeln", z[str(seiten["unter_einzeln"]["id"])], None)
        # Die Einzelfreigabe samt Unterseiten: Die Unterseite ist danach über sie veröffentlicht – abgeschwächter Globus,
        # kein Entwurf mehr, ebenfalls ohne Neuladen.
        e = seiten["einzeln"]
        assert s.klick(f'#tree li[data-id="{e["id"]}"] > .row > a') is None
        assert s.warte(f"document.querySelector('h1.seitentitel')?.textContent.startsWith({e['title']!r})", sek=10)
        assert s.klick("#pg-share") is None
        assert s.warte("!!document.querySelector('dialog[open] #sh-children:not([disabled])')", sek=10)
        assert s.klick("dialog[open] #sh-children") is None
        assert s.klick("dialog[open] #sh-save") is None
        u_id = str(seiten["unter_einzeln"]["id"])
        assert s.warte(f"!document.querySelector('dialog[open]') && !!document.querySelector('#tree li[data-id=\"{u_id}\"] .pub.geerbt')",
                       sek=10)
        z = s.js(BAUM)[u_id]
        assert not z["grau"] and not z["vorlesen"], z
        _globus_pruefen("unter_einzeln", z, "Einzeln freigegeben")
        assert not _fehler(s), _fehler(s)
    finally:
        s.schliessen()


def test_entwurf_marke():
    if uebersprungen():
        print("übersprungen – kein Chromium")
        return
    with Umgebung() as u:
        _lauf(u)


if __name__ == "__main__":
    test_entwurf_marke()
    print("ok")

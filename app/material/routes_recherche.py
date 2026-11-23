"""Routen der Recherche per Claude API an einer Produktmeldung (services/recherche.py, app/ki.py; 21.11.2026).

Alles nur für die Material-Verwaltung (B1 A, B2 A – katalog_required). Ohne Schlüssel (ki.schluessel) antworten nur Start und
Abbrechen mit 503 – was schon da ist (Stand, Vorschlag, Dateien, Übernahme, Nachladen), braucht keinen Aufruf der API
und bleibt erreichbar (Browserprüfung vom 21.11.2026, V2); GET /meldungen trägt dann „recherche“, aber kein
„recherche_moeglich“ (kein Knopf „Recherchieren lassen“). Unbekannte Meldungen: 404 wie überall. Die Dateien eines Vorschlags liefert
eine eigene Route aus (die Medienroute kennt nur Dateien mit Dokumentzeile) – mit denselben Kopfzeilen wie ein
Herstellerdokument (strenge CSP mit sandbox, nosniff, nie in einem gemeinsamen Zwischenspeicher).

Antworten (Beispiele im Bericht zum Bau):
  POST   /api/material/meldungen/<id>/recherche              {domains, fotos, bemerkung} → 202 {recherche, moeglich}
  GET    /api/material/meldungen/<id>/recherche              → {recherche (voll), moeglich, start}
  POST   /api/material/meldungen/<id>/recherche/abbrechen    → {recherche}
  GET    /api/material/meldungen/<id>/recherche/dateien/<n>  → die Datei
  POST   /api/material/meldungen/<id>/recherche/uebernehmen  {gemeinsam, ausfuehrungen, antwort} → 201
         {meldung, produkte, anhaengen, recherche}
  POST   /api/material/meldungen/<id>/recherche/nachladen    → {meldung, produkte, anhaengen, recherche}

Seit dem 22.11.2026 der Reiter „Recherche“ im Produktdialog (entwurf_recherche_reiter_produkt.md): Läufe ohne Meldung
(Bezug „mat_katalog“) liest, startet, bricht ab und verwirft er über die Kennung des Laufs; aus einer Meldung nimmt er
deren Routen oben. Nach „Anlegen“ hängt anhaengen die gewählten Dateien an – für Läufe mit und ohne Meldung. Die
Leserouten nach Kennung kennen nur Läufe ohne Meldung (sonst 404). Gleiches Recht wie oben (katalog_required): Jede
Material-Verwaltung darf jeden Lauf über seine Kennung, nur „Verwerfen“ bleibt dem, der gestartet hat (403).
  GET    /api/material/recherche?hersteller=…                → {recherche (eigener Lauf, voll) | null, moeglich, start}
  POST   /api/material/recherche   {manufacturer, model, article_no, norm, category_id, description, domains}
         → 202 {recherche, moeglich, hinweis}; 409 mit „produkt“, wenn es schon im Katalog steht
  GET    /api/material/recherche/<lid>                       → {recherche (voll), moeglich}
  POST   /api/material/recherche/<lid>/abbrechen             → {recherche}
  GET    /api/material/recherche/<lid>/dateien/<n>           → die Datei
  POST   /api/material/recherche/<lid>/anhaengen   {product_id, nr, dateien, bild, felder} → {anhaengen, recherche}
  POST   /api/material/recherche/<lid>/verwerfen             → {ok}"""
from functools import wraps

from flask import jsonify, request, send_from_directory

from .. import ki
from ..auth import json_body
from .routes import api
from .services import Abgelehnt, recherche
from .services.rechte import katalog_required

NICHT_EINGERICHTET = "Die Recherche per Claude API ist nicht eingerichtet (kein API-Schlüssel)."


def _verfuegbar(f):
    """503 ohne Schlüssel – nach der Rechteprüfung (katalog_required steht außen), damit niemand sonst etwas erfährt.
    Nur an Start und Abbrechen: Nur sie hätten mit der API zu tun."""
    @wraps(f)
    def wrapper(*a, **kw):
        if not ki.verfuegbar():
            raise Abgelehnt(NICHT_EINGERICHTET, 503)
        return f(*a, **kw)
    return wrapper


@api.post("/meldungen/<int:mid>/recherche")
@katalog_required
@_verfuegbar
def recherche_starten(mid):
    """Start → 202. 409: Meldung erledigt oder es läuft schon eine Recherche; 429: Kontingent; 400: Domains."""
    z = recherche.starten(mid, json_body())
    return jsonify(recherche=recherche.status_json(z), moeglich=recherche.moeglich()), 202


@api.get("/meldungen/<int:mid>/recherche")
@katalog_required
def recherche_lesen(mid):
    return jsonify(recherche.lesen(mid))


@api.post("/meldungen/<int:mid>/recherche/abbrechen")
@katalog_required
@_verfuegbar
def recherche_abbrechen(mid):
    """Setzt das Abbruch-Kennzeichen; der Lauf endet „abgebrochen“, sobald er es liest (im selben Arbeitsprozess
    sofort, sonst mit dem nächsten Lebenszeichen). 409, wenn er nicht mehr läuft."""
    return jsonify(recherche=recherche.status_json(recherche.abbrechen(mid)))


@api.get("/meldungen/<int:mid>/recherche/dateien/<int:n>")
@katalog_required
def recherche_datei(mid, n):
    return _datei(*recherche.datei(mid, n))


def _datei(ordner, name, mime):
    """Eine Datei eines Vorschlags – mit den Kopfzeilen eines Herstellerdokuments."""
    resp = send_from_directory(ordner, name, mimetype=mime, as_attachment=False, download_name=name, max_age=0)
    resp.cache_control.public = None
    resp.cache_control.private = True
    resp.cache_control.no_store = True
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@api.post("/meldungen/<int:mid>/recherche/uebernehmen")
@katalog_required
def recherche_uebernehmen(mid):
    """Legt die gewählten Ausführungen als Produkte an und erledigt die Meldung (201); schon übernommen: hängt nur
    fehlende Dateien an (200)."""
    schon = (recherche._lauf(mid) or {}).get("status") == "uebernommen"
    return jsonify(recherche.uebernehmen(mid, json_body())), 200 if schon else 201


@api.post("/meldungen/<int:mid>/recherche/nachladen")
@katalog_required
def recherche_nachladen(mid):
    return jsonify(recherche.nachladen(mid))


# --- Reiter „Recherche“ im Produktdialog (22.11.2026) ---------------------------------------------------------------

@api.get("/recherche")
@katalog_required
def recherche_eigene():
    """Der eigene Lauf ohne Meldung; „hersteller“ (aus dem Formular) belegt die Domains des Starts vor."""
    return jsonify(recherche.katalog_lesen(request.args.get("hersteller", "")[:120]))


@api.post("/recherche")
@katalog_required
@_verfuegbar
def recherche_katalog_starten():
    """Start ohne Meldung → 202. 400 Feld, 409 im Katalog („produkt“) oder es läuft schon eine, 429 Kontingent."""
    try:
        z, hinweis = recherche.katalog_starten(json_body())
    except recherche.ImKatalog as exc:
        return jsonify(error=str(exc), produkt=exc.produkt), 409
    return jsonify(recherche=recherche.status_json(z), moeglich=recherche.moeglich(), hinweis=hinweis), 202


@api.get("/recherche/<int:lid>")
@katalog_required
def recherche_lauf(lid):
    return jsonify(recherche.lauf_lesen(lid))


@api.post("/recherche/<int:lid>/abbrechen")
@katalog_required
@_verfuegbar
def recherche_lauf_abbrechen(lid):
    return jsonify(recherche=recherche.status_json(recherche.lauf_abbrechen(lid)))


@api.get("/recherche/<int:lid>/dateien/<int:n>")
@katalog_required
def recherche_lauf_datei(lid, n):
    return _datei(*recherche.lauf_datei(lid, n))


@api.post("/recherche/<int:lid>/anhaengen")
@katalog_required
def recherche_anhaengen(lid):
    """Nach „Anlegen“ im Produktdialog: die gewählten Dateien an das neue Produkt (Läufe mit und ohne Meldung)."""
    return jsonify(recherche.anhaengen(lid, json_body()))


@api.post("/recherche/<int:lid>/verwerfen")
@katalog_required
def recherche_verwerfen(lid):
    return jsonify(recherche.verwerfen(lid))

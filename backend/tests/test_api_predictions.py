"""Integración: endpoints de predicción del modelo (servicio de inferencia)."""
from __future__ import annotations


def test_fixtures_list_public(client):
    r = client.get("/v1/fixtures")
    assert r.status_code == 200
    assert isinstance(r.json(), list) and r.json()


def test_fixture_prediction_probabilities_sum_to_one(client, scheduled_fixture_id):
    r = client.get(f"/v1/fixtures/{scheduled_fixture_id}/prediction")
    assert r.status_code == 200, r.text
    p = r.json()["markets"]["1x2"]
    total = p["home"]["prob"] + p["draw"]["prob"] + p["away"]["prob"]
    assert abs(total - 1.0) < 1e-3


def test_fixture_prediction_404_for_unknown(client):
    assert client.get("/v1/fixtures/999999/prediction").status_code == 404


def test_fixtures_predictions_batch(client):
    r = client.get("/v1/fixtures/predictions")
    assert r.status_code == 200


def test_predict_adhoc_unknown_team_422(client):
    r = client.get("/v1/predict", params={"home": "Narnia", "away": "Mordor"})
    assert r.status_code in (422, 200)  # 422 si el equipo no existe en el modelo


def test_tournament_champion(client):
    r = client.get("/v1/tournament/champion")
    assert r.status_code == 200

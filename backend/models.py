from dataclasses import dataclass
from typing import Optional, List
import json


@dataclass
class Annuncio:
    id: int
    indirizzo: str
    indirizzo_preciso: bool
    zona: str
    tipo: str
    mq: Optional[int]
    camere: Optional[int]
    prezzo: Optional[int]
    giorni_online: int
    fonte: str  # "privato", "agenzia", "noescl"
    agenzie: List[str]
    proprietario: Optional[str]
    telefono: Optional[str]
    intel_privato: Optional[str]
    intel_warning: Optional[str]
    ai_insight: Optional[str]
    is_nuovo: bool
    data_inserimento: str
    url_originale: Optional[str]
    foto_url: Optional[str]       # prima foto (backward compat)
    foto_urls: List[str]          # tutte le foto (galleria)

    @staticmethod
    def from_row(row: dict) -> "Annuncio":
        agenzie = row.get("agenzie") or "[]"
        if isinstance(agenzie, str):
            try:
                agenzie = json.loads(agenzie)
            except Exception:
                agenzie = []

        # foto_url può essere una singola URL (vecchio) o JSON array (nuovo)
        raw_foto = row.get("foto_url") or ""
        if raw_foto.startswith("["):
            try:
                foto_urls = [u for u in json.loads(raw_foto) if u]
            except Exception:
                foto_urls = []
        else:
            foto_urls = [raw_foto] if raw_foto else []
        foto_url = foto_urls[0] if foto_urls else None

        return Annuncio(
            id=row["id"],
            indirizzo=row["indirizzo"],
            indirizzo_preciso=bool(row["indirizzo_preciso"]),
            zona=row.get("zona") or "",
            tipo=row.get("tipo") or "",
            mq=row.get("mq"),
            camere=row.get("camere"),
            prezzo=row.get("prezzo"),
            giorni_online=row.get("giorni_online") or 0,
            fonte=row.get("fonte") or "agenzia",
            agenzie=agenzie,
            proprietario=row.get("proprietario"),
            telefono=row.get("telefono"),
            intel_privato=row.get("intel_privato"),
            intel_warning=row.get("intel_warning"),
            ai_insight=row.get("ai_insight"),
            is_nuovo=bool(row.get("is_nuovo")),
            data_inserimento=str(row.get("data_inserimento") or ""),
            url_originale=row.get("url_originale"),
            foto_url=foto_url,
            foto_urls=foto_urls,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "indirizzo": self.indirizzo,
            "indirizzo_preciso": self.indirizzo_preciso,
            "zona": self.zona,
            "tipo": self.tipo,
            "mq": self.mq,
            "camere": self.camere,
            "prezzo": self.prezzo,
            "giorni_online": self.giorni_online,
            "fonte": self.fonte,
            "agenzie": self.agenzie,
            "proprietario": self.proprietario,
            "telefono": self.telefono,
            "intel_privato": self.intel_privato,
            "intel_warning": self.intel_warning,
            "ai_insight": self.ai_insight,
            "is_nuovo": self.is_nuovo,
            "data_inserimento": self.data_inserimento,
            "url_originale": self.url_originale,
            "foto_url": self.foto_url,
            "foto_urls": self.foto_urls,
        }

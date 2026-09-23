from datetime import datetime

import httpx

from biostar.models import BioStarUser
from biostar.settings import BioStarConnectionSettings


class BioStarClient:
    """BioStar 2 New Local API salt-okunur istemcisi."""

    def __init__(self, settings: BioStarConnectionSettings, password: str) -> None:
        self._settings = settings
        self._password = password
        self._session_id: str | None = None
        self._http = httpx.Client(
            base_url=settings.normalized_url(),
            verify=settings.verify_certificate,
            timeout=10.0,
            headers={"Accept": "application/json"},
        )

    def login(self) -> None:
        response = self._http.post(
            "/api/login",
            json={
                "User": {
                    "login_id": self._settings.username,
                    "password": self._password,
                }
            },
        )
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "BioStar girişi başarısız."))
        session_id = response.headers.get("bs-session-id")
        if not session_id:
            raise RuntimeError("BioStar cevabında bs-session-id bulunamadı.")
        self._session_id = session_id
        self._http.headers["bs-session-id"] = session_id

    def list_users(self, group_id: str | None = None) -> list[BioStarUser]:
        if not self._session_id:
            self.login()
        params = {"limit": 0, "offset": 0}
        if group_id:
            params["group_id"] = group_id
        response = self._http.get("/api/users", params=params)
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) == "10":
            self.login()
            return self.list_users(group_id)
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kullanıcı listesi alınamadı."))

        rows = payload.get("UserCollection", {}).get("rows", [])
        return [
            BioStarUser(
                user_id=str(row.get("user_id", "")),
                name=str(row.get("name", "")),
                card_count=int(row.get("card_count") or 0),
                start_datetime=str(row.get("start_datetime", "")),
                expiry_datetime=str(row.get("expiry_datetime", "")),
                disabled=self._as_bool(row.get("disabled", False)),
                user_group_id=self._object_field(row.get("user_group_id"), "id"),
                user_group_name=self._object_field(row.get("user_group_id"), "name"),
            )
            for row in rows
        ]

    def move_user_to_group(self, user_id: str, user_group_id: str) -> None:
        if str(user_id) == "1":
            raise ValueError("BioStar yönetici kullanıcısının grubu değiştirilemez.")
        response = self._http.put(
            f"/api/users/{user_id}",
            json={"User": {"user_group_id": {"id": str(user_group_id)}}},
        )
        self._raise_for_status_with_detail(response, "Kullanıcı grubu değiştirilemedi")
        payload = response.json() if response.content else {}
        api_response = payload.get("Response", {})
        if api_response and str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kullanıcı grubu değiştirilemedi."))

    def get_user_detail(self, user_id: str) -> dict:
        """Tek kullanıcının kartlar dahil detayını salt-okunur getirir."""
        if not self._session_id:
            self.login()
        response = self._http.get(f"/api/users/{user_id}")
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) == "10":
            self.login()
            return self.get_user_detail(user_id)
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kullanıcı detayı alınamadı."))
        return payload.get("User", {})

    def try_get_user_detail(self, user_id: str) -> dict | None:
        """Kullanıcı yoksa None, varsa detayını döndürür."""
        try:
            return self.get_user_detail(user_id)
        except httpx.HTTPStatusError as error:
            # BioStar 2, bulunamayan geçerli bir kullanıcı için sürüme göre
            # 400 veya 404 döndürebiliyor.
            if error.response.status_code in {400, 404}:
                return None
            raise

    def find_user_by_name(self, name: str) -> BioStarUser | None:
        matches = [user for user in self.list_users() if user.name == name]
        if len(matches) > 1:
            raise RuntimeError(f"BioStar'da '{name}' adında birden fazla kullanıcı bulundu.")
        return matches[0] if matches else None

    def get_next_user_id(self) -> str:
        """Sunucu başlangıç değeri yerine ilk kullanılmayan pozitif sayısal ID'yi bulur."""
        numeric_ids = {
            int(user.user_id)
            for user in self.list_users()
            if str(user.user_id).isdigit()
        }
        candidate = 1
        while candidate in numeric_ids:
            candidate += 1
        return str(candidate)

    def delete_user(self, user_id: str) -> None:
        """Tek bir BioStar kullanıcısını siler; kart kaydını ayrıca silmez."""
        if str(user_id) == "1":
            raise ValueError("BioStar yönetici kullanıcısı silinemez.")
        if not self._session_id:
            self.login()
        response = self._http.delete("/api/users", params={"id": str(user_id)})
        self._raise_for_status_with_detail(response, "BioStar kullanıcısı silinemedi")
        if not response.content:
            return
        payload = response.json()
        api_response = payload.get("Response", {})
        if api_response and str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "BioStar kullanıcısı silinemedi."))

    def list_unassigned_cards(self) -> list[dict]:
        if not self._session_id:
            self.login()
        response = self._http.get("/api/cards/unassigned", params={"limit": 0, "offset": 0})
        self._raise_for_status_with_detail(response, "Sahipsiz kartlar alınamadı")
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Sahipsiz kartlar alınamadı."))
        collection = payload.get("CardCollection", {})
        rows = collection.get("rows", []) if isinstance(collection, dict) else collection
        return rows if isinstance(rows, list) else []

    def delete_unassigned_card(self, internal_card_id: str) -> None:
        response = self._http.delete("/api/cards", params={"id": str(internal_card_id)})
        self._raise_for_status_with_detail(response, "Sahipsiz kart silinemedi")
        if response.content:
            payload = response.json()
            api_response = payload.get("Response", {})
            if api_response and str(api_response.get("code", "")) != "0":
                raise RuntimeError(api_response.get("message", "Sahipsiz kart silinemedi."))

    def get_wiegand_format(self, format_id: str) -> dict:
        """Bir Wiegand formatının tanımını salt-okunur getirir."""
        if not self._session_id:
            self.login()
        response = self._http.get(f"/api/cards/wiegand_formats/{format_id}")
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) == "10":
            self.login()
            return self.get_wiegand_format(format_id)
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Wiegand formatı alınamadı."))
        return payload.get("WiegandFormat", {})

    def find_card(self, card_id: int) -> dict | None:
        response = self._http.get("/api/cards", params={"query": str(card_id)})
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("CardCollection", {}).get("rows", [])
        for card in rows:
            if str(card.get("card_id")) == str(card_id):
                return card
        return None

    def list_access_groups(self) -> list[dict]:
        """Tanımlı erişim gruplarını değişiklik yapmadan getirir."""
        if not self._session_id:
            self.login()
        response = self._http.get("/api/access_groups")
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) == "10":
            self.login()
            return self.list_access_groups()
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Erişim grupları alınamadı."))
        collection = payload.get("AccessGroupCollection", {})
        rows = collection.get("rows", []) if isinstance(collection, dict) else collection
        return rows if isinstance(rows, list) else []

    def list_user_groups(self) -> list[dict]:
        """BioStar kullanıcı gruplarını değişiklik yapmadan getirir."""
        if not self._session_id:
            self.login()
        response = self._http.get("/api/user_groups", params={"limit": 0, "offset": 0})
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) == "10":
            self.login()
            return self.list_user_groups()
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kullanıcı grupları alınamadı."))
        collection = payload.get("UserGroupCollection", {})
        rows = collection.get("rows", []) if isinstance(collection, dict) else collection
        return rows if isinstance(rows, list) else []

    def create_wiegand26_card(self, card_id: int) -> dict:
        response = self._http.post(
            "/api/cards",
            json={
                "CardCollection": {
                    "rows": [
                        {
                            "card_id": str(card_id),
                            "card_type": {"id": "1", "type": "10"},
                            "wiegand_format_id": {"id": "0"},
                        }
                    ]
                }
            },
        )
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kart oluşturulamadı."))
        rows = payload.get("CardCollection", {}).get("rows", [])
        if not rows or not rows[0].get("id"):
            raise RuntimeError("BioStar yeni kartın dahili ID değerini döndürmedi.")
        return rows[0]

    def assign_card_to_user(self, user_id: str, internal_card_id: str) -> None:
        user = self.get_user_detail(user_id)
        cards_value = user.get("cards", [])
        cards = cards_value.get("rows", []) if isinstance(cards_value, dict) else cards_value
        existing_ids = [str(card.get("id")) for card in cards if card.get("id")]
        if str(internal_card_id) not in existing_ids:
            existing_ids.append(str(internal_card_id))
        response = self._http.put(
            f"/api/users/{user_id}",
            json={"User": {"cards": [{"id": value} for value in existing_ids]}},
        )
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kart kullanıcıya atanamadı."))

    @staticmethod
    def _as_bool(value: object) -> bool:
        return value is True or str(value).lower() in {"1", "true", "yes"}

    @staticmethod
    def _object_field(value: object, field: str) -> str:
        return str(value.get(field, "")) if isinstance(value, dict) else ""

    def update_user_stay(
        self,
        user_id: str,
        activation: datetime,
        expiration: datetime,
        access_group_id: str,
    ) -> None:
        """Kullanıcının tarihlerini ve tek erişim grubunu günceller."""
        if expiration <= activation:
            raise ValueError("Bitiş zamanı başlangıç zamanından sonra olmalıdır.")
        if not access_group_id:
            raise ValueError("BioStar erişim grubu seçilmemiş.")
        response = self._http.put(
            f"/api/users/{user_id}",
            json={"User": {
                "start_datetime": self._to_biostar_utc(activation),
                "expiry_datetime": self._to_biostar_utc(expiration),
                "access_groups": [{"id": str(access_group_id)}],
            }},
        )
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kullanıcı tarihleri güncellenemedi."))

    @staticmethod
    def _to_biostar_utc(value: datetime) -> str:
        return value.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.00Z")

    def assign_card_and_stay(
        self,
        user_id: str,
        internal_card_id: str,
        activation: datetime,
        expiration: datetime,
        access_group_id: str,
    ) -> None:
        """Mevcut kartları koruyarak kart, tarih ve erişim grubunu tek istekte yazar."""
        user = self.get_user_detail(user_id)
        cards_value = user.get("cards", [])
        cards = cards_value.get("rows", []) if isinstance(cards_value, dict) else cards_value
        existing_ids = [str(card.get("id")) for card in cards if card.get("id")]
        if str(internal_card_id) not in existing_ids:
            existing_ids.append(str(internal_card_id))
        if expiration <= activation:
            raise ValueError("Bitiş zamanı başlangıç zamanından sonra olmalıdır.")
        if not access_group_id:
            raise ValueError("BioStar erişim grubu seçilmemiş.")
        response = self._http.put(
            f"/api/users/{user_id}",
            json={"User": {
                "cards": [{"id": value} for value in existing_ids],
                "start_datetime": self._to_biostar_utc(activation),
                "expiry_datetime": self._to_biostar_utc(expiration),
                "access_groups": [{"id": str(access_group_id)}],
            }},
        )
        response.raise_for_status()
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", "Kart ve konaklama bilgileri güncellenemedi."))

    def create_or_update_room_user(
        self,
        room_reference: str,
        internal_card_ids: list[str],
        activation: datetime,
        expiration: datetime,
        access_group_id: str,
        user_group_id: str,
    ) -> tuple[str, str]:
        """Oda adını eşleştirir; yeni kullanıcı ID'sini BioStar'dan alır."""
        matched_user = self.find_user_by_name(room_reference)
        if not user_group_id:
            raise ValueError("BioStar kullanıcı grubu seçilmemiş.")
        user_id = matched_user.user_id if matched_user else self.get_next_user_id()
        existing = self.get_user_detail(user_id) if matched_user else None
        all_card_ids = list(dict.fromkeys(str(value) for value in internal_card_ids))
        fields = {
            "start_datetime": self._to_biostar_utc(activation),
            "expiry_datetime": self._to_biostar_utc(expiration),
            "disabled": False,
            "cards": [{"id": value} for value in all_card_ids],
            "access_groups": [{"id": str(access_group_id)}],
            "user_group_id": {"id": str(user_group_id)},
        }
        if existing:
            response = self._http.put(f"/api/users/{user_id}", json={"User": fields})
            action = "güncellenemedi"
        else:
            fields.update({
                "user_id": user_id,
                "name": room_reference,
            })
            response = self._http.post("/api/users", json={"User": fields})
            action = "oluşturulamadı"
        self._raise_for_status_with_detail(response, "Oda kullanıcısı yazılamadı")
        payload = response.json()
        api_response = payload.get("Response", {})
        if str(api_response.get("code", "")) != "0":
            raise RuntimeError(api_response.get("message", f"Oda kullanıcısı {action}."))
        return ("updated" if existing else "created", user_id)

    @staticmethod
    def _raise_for_status_with_detail(response: httpx.Response, operation: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = response.text.strip()
            if len(detail) > 1200:
                detail = detail[:1200] + "…"
            raise RuntimeError(
                f"{operation} (HTTP {response.status_code}).\nBioStar cevabı: {detail or 'Boş cevap'}"
            ) from error

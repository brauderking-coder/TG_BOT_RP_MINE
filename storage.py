# storage.py
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from config import ROLES, DATA_PATH

logger = logging.getLogger(__name__)


class RoleStore:
    def __init__(self, json_path: Path):
        self.path = Path(json_path)
        self.data = {"roles": {}, "players": []}
        self._load()
        self._init_roles()
        self._recount_taken_from_players()

    # --- low-level io ---

    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Ошибка чтения JSON: {e}")

        if not isinstance(self.data, dict):
            self.data = {"roles": {}, "players": []}

        self.data.setdefault("roles", {})
        self.data.setdefault("players", [])
        if not isinstance(self.data["roles"], dict):
            self.data["roles"] = {}
        if not isinstance(self.data["players"], list):
            self.data["players"] = []

    def _atomic_write_text(self, text: str):
        """
        Атомарная запись через temp-file + replace.
        ВАЖНО для Windows: mkstemp возвращает fd, его надо закрыть,
        иначе replace/удаление может дать WinError 32. [web:63][web:67]
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.stem}_",
            suffix=self.path.suffix,
        )
        tmp_path = Path(tmp_name)

        try:
            os.close(fd)  # критично для Windows

            with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())

            # replace поверх существующего файла
            os.replace(str(tmp_path), str(self.path))
        finally:
            # если что-то упало до replace — подчистим temp
            try:
                if tmp_path.exists() and tmp_path != self.path:
                    tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _save(self):
        payload = json.dumps(self.data, indent=2, ensure_ascii=False)
        self._atomic_write_text(payload)

    # --- data normalization ---

    def _init_roles(self):
        for role, cap in ROLES.items():
            if role not in self.data["roles"] or not isinstance(self.data["roles"][role], dict):
                self.data["roles"][role] = {"capacity": int(cap), "taken": 0}
            else:
                self.data["roles"][role]["capacity"] = int(cap)
                self.data["roles"][role].setdefault("taken", 0)

        self._save()

    def _recount_taken_from_players(self):
        for role in self.data["roles"].keys():
            self.data["roles"][role]["taken"] = 0

        for p in self.data["players"]:
            status = p.get("status")
            role = p.get("role")
            if role in self.data["roles"] and status in ("role_selected", "waiting_minecraft_name", "registered"):
                self.data["roles"][role]["taken"] += 1

        for role, v in self.data["roles"].items():
            cap = int(v.get("capacity", 0))
            taken = int(v.get("taken", 0))
            if taken < 0:
                v["taken"] = 0
            if cap >= 0 and v["taken"] > cap:
                v["taken"] = cap

        self._save()

    # --- public api ---

    def get_all_roles(self):
        return [(r, v["capacity"], v["taken"]) for r, v in self.data["roles"].items()]

    def get_free_roles(self):
        return [
            (r, v["capacity"], v["taken"])
            for r, v in self.data["roles"].items()
            if int(v.get("taken", 0)) < int(v.get("capacity", 0))
        ]

    def get_free_slots_count(self):
        return sum(int(v["capacity"]) - int(v["taken"]) for v in self.data["roles"].values())

    def get_players_by_role(self):
        roles = {}
        for p in self.data["players"]:
            if p.get("status") == "registered" and p.get("role"):
                roles.setdefault(p["role"], []).append(p)
        return roles

    def get_player(self, telegram_id: int):
        for p in self.data["players"]:
            if p.get("telegram_id") == telegram_id:
                return p
        return None

    def get_player_role(self, telegram_id: int):
        p = self.get_player(telegram_id)
        return p.get("role") if p else None

    def _player_occupies_slot(self, p: dict) -> bool:
        return (
            p.get("status") in ("role_selected", "waiting_minecraft_name", "registered")
            and p.get("role") in self.data["roles"]
        )

    def _safe_dec_taken(self, role: str):
        if role in self.data["roles"]:
            self.data["roles"][role]["taken"] = max(0, int(self.data["roles"][role].get("taken", 0)) - 1)

    def _safe_inc_taken(self, role: str):
        if role in self.data["roles"]:
            cap = int(self.data["roles"][role].get("capacity", 0))
            taken = int(self.data["roles"][role].get("taken", 0))
            self.data["roles"][role]["taken"] = min(cap, taken + 1)

    def assign_role(self, telegram_id: int, username: str, new_role: str):
        if new_role not in self.data["roles"]:
            return False, "Такой роли нет."

        cap = int(self.data["roles"][new_role]["capacity"])
        taken = int(self.data["roles"][new_role]["taken"])
        if taken >= cap:
            return False, "Роль заполнена!"

        player = self.get_player(telegram_id)

        if player:
            old_role = player.get("role")
            if old_role == new_role and player.get("status") in ("role_selected", "waiting_minecraft_name", "registered"):
                return True, "Роль уже выбрана."

            if self._player_occupies_slot(player) and old_role in self.data["roles"]:
                self._safe_dec_taken(old_role)

            player["username"] = username
            player["role"] = new_role
            player["status"] = "role_selected"
            player.setdefault("rp_name", None)
            player.setdefault("minecraft_username", None)
            player["timestamp"] = datetime.now().isoformat()
        else:
            player = {
                "telegram_id": telegram_id,
                "username": username,
                "rp_name": None,
                "minecraft_username": None,
                "role": new_role,
                "status": "role_selected",
                "timestamp": datetime.now().isoformat(),
            }
            self.data["players"].append(player)

        self._safe_inc_taken(new_role)
        self._save()
        return True, "Роль назначена."

    def set_rp_name(self, telegram_id: int, rp_name: str):
        p = self.get_player(telegram_id)
        if not p or p.get("status") != "role_selected":
            return False

        p["rp_name"] = rp_name
        p["status"] = "waiting_minecraft_name"
        p["timestamp"] = datetime.now().isoformat()
        self._save()
        return True

    def set_minecraft_name(self, telegram_id: int, minecraft_name: str):
        p = self.get_player(telegram_id)
        if not p or p.get("status") != "waiting_minecraft_name":
            return False

        p["minecraft_username"] = minecraft_name
        p["status"] = "registered"
        p["timestamp"] = datetime.now().isoformat()
        self._save()
        return True

    def add_to_waitlist(self, telegram_id: int, username: str):
        p = self.get_player(telegram_id)
        if p:
            if self._player_occupies_slot(p):
                old_role = p.get("role")
                if old_role in self.data["roles"]:
                    self._safe_dec_taken(old_role)

            p["username"] = username
            p["role"] = None
            p["status"] = "waitlist"
            p.setdefault("rp_name", None)
            p.setdefault("minecraft_username", None)
            p["timestamp"] = datetime.now().isoformat()
        else:
            self.data["players"].append({
                "telegram_id": telegram_id,
                "username": username,
                "rp_name": None,
                "minecraft_username": None,
                "role": None,
                "status": "waitlist",
                "timestamp": datetime.now().isoformat(),
            })

        self._save()
        return True

    def remove_player(self, telegram_id: int):
        players = self.data["players"]
        for i, p in enumerate(players):
            if p.get("telegram_id") == telegram_id:
                if self._player_occupies_slot(p):
                    role = p.get("role")
                    if role in self.data["roles"]:
                        self._safe_dec_taken(role)

                del players[i]
                self._save()
                return True
        return False

    def reset_player_registration(self, telegram_id: int):
        p = self.get_player(telegram_id)
        if not p:
            return False

        if self._player_occupies_slot(p):
            old_role = p.get("role")
            if old_role in self.data["roles"]:
                self._safe_dec_taken(old_role)

        p["rp_name"] = None
        p["minecraft_username"] = None
        p["role"] = None
        p["status"] = "start"
        p["timestamp"] = datetime.now().isoformat()

        self._save()
        return True


db = RoleStore(DATA_PATH)
user_states = {}

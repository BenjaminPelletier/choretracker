from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class User:
    username: str
    password: Optional[str] = None
    permissions: Set[str] = field(default_factory=set)


class UserStore:
    def __init__(self, initial_users: Optional[List[User]] = None):
        self.users: Dict[str, User] = {u.username: u for u in initial_users or []}

    def list_users(self) -> List[User]:
        return list(self.users.values())

    def get(self, username: str) -> Optional[User]:
        return self.users.get(username)

    def create(self, user: User) -> None:
        self.users[user.username] = user

    def update(self, old_username: str, user: User) -> None:
        if old_username != user.username:
            self.users.pop(old_username, None)
        self.users[user.username] = user

    def delete(self, username: str) -> None:
        self.users.pop(username, None)

    def has_permission(self, username: str, permission: str) -> bool:
        user = self.get(username)
        return permission in user.permissions if user else False

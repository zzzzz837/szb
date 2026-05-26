import os
from dotenv import load_dotenv
load_dotenv()
v = os.getenv("GROUP_INVITE_LINK", "")
print(f"GROUP_INVITE_LINK = '{v}'")

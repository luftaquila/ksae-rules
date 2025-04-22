import re
import zipfile
import requests
import urllib.parse
from lxml import html
from pathlib import Path
from environs import Env

env = Env()
env.read_env()

class Client:
    def __init__(self, *, domain="", project_id="", username="", password=""):
        if domain == "" or project_id == "" or username == "" or password == "":
            raise Exception("domain, project_id, username and password are required")

        self.domain = domain
        self.project_id = project_id
        self.username = username
        self.password = password

        self.client = requests.session()
        self.login_data, self.cookie = self.authenticate()

    def sync(self):
        r = self.client.get(f"{self.domain}/project/{self.project_id}/download/zip", stream=True)
        zip = Path(f"{self.project_id}.zip")

        with open(zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)

        with zipfile.ZipFile(zip) as zip_file:
            zip_file.extractall('../')

        zip.unlink()

    def authenticate(self, login_path="/login"):
        login_url = urllib.parse.urljoin(self.domain, login_path)

        r = self.client.get(login_url, verify=True)
        csrf = self.get_csrf_Token(r.text)

        if csrf is None:
            raise Exception(f"No CSRF in {login_url}")

        self.csrf = csrf
        self.login_data = dict(email=self.username, password=self.password, _csrf=self.csrf)

        r = self.client.post(login_url, data=self.login_data, verify=True)
        r.raise_for_status()

        csrf = self.get_csrf_Token(r.text)

        if csrf is None:
            raise Exception(f"No CSRF in {login_url}")

        login_data = dict(email=self.username, _csrf=csrf)

        return login_data, {"overleaf.sid": r.cookies["overleaf.sid"]}

    def get_csrf_Token(self, html_str):
        if "csrfToken" in html_str:
            csrf_token = re.search('(?<=csrfToken = ").{36}', html_str)

            if csrf_token is not None:
                return csrf_token.group(0)
            else:
                parsed = html.fromstring(html_str)
                meta = parsed.xpath("//meta[@name='ol-csrfToken']")
                if meta:
                    return meta[0].get("content")
        return None

client = Client(domain=env("DOMAIN"), project_id=env("PROJECT_ID"), username=env("EMAIL"), password=env("PASSWORD"))
client.sync()

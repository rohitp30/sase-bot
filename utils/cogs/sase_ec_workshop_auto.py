import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle

# QR generator lives elsewhere
from core.common import generate_qr_with_logo


# =========================
# CONFIG
# =========================
DESTINATION_PARENT_FOLDER_ID = "1Z85uVNnFj7vLGAWVeD6oVZjjyQjpWQkv"
TEMPLATE_FOLDER_ID = "1I5s1TV0XqTDkfDmutXVFa7q3sjQ4v--p"

SASE_LOGO_PATH = "assets/sase_logo_v3.png"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/presentations",
]


# =========================
# GOOGLE CLIENT
# =========================

TOKEN_FILE = "credentials/token.pickle"
CLIENT_SECRET_FILE = "credentials/oauth_client.json"

def get_google_services():
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        creds.refresh(Request())
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    drive = build("drive", "v3", credentials=creds)
    forms = build("forms", "v1", credentials=creds)
    slides = build("slides", "v1", credentials=creds)

    return drive, forms, slides


# =========================
# DISCORD COG
# =========================

class WorkshopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.drive, self.forms, self.slides = get_google_services()


    EC = app_commands.Group(
        name="ec",
        description="Commands for SASE Event Committee.",
        guild_ids=[1376018416934322176, 1223473430410690630],
    )

    @EC.command(description="Create exam workshop assets.")
    async def create_exam_workshop(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            WorkshopModal(self.drive, self.forms, self.slides)
        )

    @EC.command(name="make_qr", description="Generate a QR code with the SASE logo.")
    async def make_qr(self, interaction: discord.Interaction, url: str, custom_background: discord.Attachment = None):
        ec_member = interaction.guild.get_role(1376018416934322177)
        if ec_member not in interaction.user.roles:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        temp_path = "/tmp/qr.png"
        logo_path = SASE_LOGO_PATH

        if custom_background:
            logo_path = f"/tmp/{custom_background.filename}"
            with open(logo_path, "wb") as f:
                f.write(await custom_background.read())

        generate_qr_with_logo(url, temp_path, logo_path)

        file = discord.File(temp_path, filename="qr.png")
        await interaction.followup.send("Here is your QR code:", file=file)


class WorkshopModal(discord.ui.Modal, title="New Exam Workshop"):
    class_name = discord.ui.TextInput(label="Class (e.g. Multi)")
    exam_number = discord.ui.TextInput(label="Exam Number (e.g. 1)")
    date = discord.ui.TextInput(label="Date (e.g. Sunday, February 1st)")

    def __init__(self, drive, forms, slides):
        super().__init__()
        self.drive = drive
        self.forms = forms
        self.slides = slides

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(f"{interaction.user.mention} hold on this might take a bit...", ephemeral=True)

        class_name = self.class_name.value.strip()
        exam_number = self.exam_number.value.strip()
        date = self.date.value.strip()

        result = await asyncio.to_thread(
            create_exam_workshop_assets,
            self.drive,
            self.forms,
            self.slides,
            class_name,
            exam_number,
            date,
        )
        embed = discord.Embed(
            title=f"{class_name} Exam {exam_number} Workshop Created",
            description="The exam workshop assets have been successfully created.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Asset Links",
            value=f"""
            [📂 Drive Folder](https://drive.google.com/drive/folders/{result['folder_id']})
            [📊 Slides](https://docs.google.com/presentation/d/{result['slides_id']})
            [📝 Feedback Form](https://docs.google.com/forms/d/{result['form_id']})\n\n
            **Remaining Tasks:**
- You'll still need to **publish** the Feedback Form to make it accessible to students.
 - **Update** the Feedback Form QR on the Slides with the **published** form link.
- Update the Slides with any other information specific to the exam workshop as needed.
- Upload any additional resources to the Drive folder as needed. (Blank exam & written solutions docs have already been created for you.)
\n\n**🚨 To modify/create QR codes, you can use the `/ec make_qr` command in this server.**
            """,
            inline=False,
        )
        embed.set_footer(text=f"Exam Workshop Created by {interaction.user}")
        await interaction.followup.send(embed=embed)


# =========================
# CORE WORKFLOW
# =========================

def create_exam_workshop_assets(drive, forms, slides, class_name, exam_number, date):
    dest_folder_id = create_destination_folder(
        drive, class_name, exam_number, date
    )

    copied_files = copy_template_files(
        drive, TEMPLATE_FOLDER_ID, dest_folder_id, class_name, exam_number
    )

    update_feedback_form(
        forms,
        copied_files["form_id"],
        class_name,
        exam_number,
        date,
    )

    update_slides(
        drive,
        slides,
        copied_files,
        dest_folder_id,
        class_name,
        exam_number,
        date
    )

    return {
        "folder_id": dest_folder_id,
        "slides_id": copied_files["slides_id"],
        "form_id": copied_files["form_id"],
    }


# =========================
# DRIVE LOGIC
# =========================

def create_destination_folder(drive, class_name, exam_number, date):
    folder = drive.files().create(
        body={
            "name": f"{class_name} Exam {exam_number} - {date}",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [DESTINATION_PARENT_FOLDER_ID],
        },
        supportsAllDrives = True,
    ).execute()

    return folder["id"]


def copy_template_files(drive, template_folder_id, dest_folder_id, class_name, exam_number):
    files = drive.files().list(
        q=f"'{template_folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()["files"]

    result = {}

    for f in files:
        mime = f["mimeType"]
        original_name = f["name"].lower()

        if mime == "application/vnd.google-apps.form":
            name = f"S26 SASE {class_name} Exam {exam_number} Feedback Form"
        elif mime == "application/vnd.google-apps.presentation":
            name = f"S26 SASE {class_name} Exam {exam_number} Review Slides"
        elif mime == "application/vnd.google-apps.document":
            if "blank" in original_name:
                name = f"{class_name} Exam {exam_number} BLANK"
            elif "written" in original_name:
                name = f"S26 SASE {class_name} Exam Written Solutions"
        else:
            raise ValueError(f"Unknown document template: {f['name']}")

        copied = drive.files().copy(
            fileId=f["id"],
            body={"name": name, "parents": [dest_folder_id]},
            supportsAllDrives=True,
        ).execute()

        if mime == "application/vnd.google-apps.form":
            result["form_id"] = copied["id"]
        elif mime == "application/vnd.google-apps.presentation":
            result["slides_id"] = copied["id"]
        elif mime == "application/vnd.google-apps.document":
            result["written_doc_id"] = copied["id"]

            # Make the document shareable via link
            drive.permissions().create(
                fileId=copied["id"],
                body={
                    "type": "anyone",
                    "role": "reader",
                },
                supportsAllDrives=True,
            ).execute()

    return result


# =========================
# FORM LOGIC
# =========================

def update_feedback_form(forms, form_id, class_name, exam_number, date):
    forms.forms().batchUpdate(
        formId=form_id,
        body={
            "requests": [
                {
                    "updateFormInfo": {
                        "info": {
                            "title": f"{class_name} Exam {exam_number} Feedback Form",
                            "description": (
                                f"Thank you for attending our {class_name} Exam "
                                f"{exam_number} review this {date}.\n\n"
                                "Please feel free to leave any feedback, questions, "
                                "or comments you may have for our instructor. :)\n\n"
                                "Linktree: https://linktr.ee/saserpi"
                            ),
                        },
                        "updateMask": "title,description",
                    }
                }
            ]
        },
    ).execute()


# =========================
# SLIDES LOGIC
# =========================

def update_slides(drive, slides_service, files, folder_id, class_name, exam_number, date):
    slides_id = files["slides_id"]

    # Generate QR codes (paths only; implementation elsewhere)
    generate_qr_with_logo(
        f"https://docs.google.com/document/d/{files['written_doc_id']}/edit?usp=sharing",
        "/tmp/written_qr.png",
        SASE_LOGO_PATH,
    )

    written_qr_url = upload_image(drive, "/tmp/written_qr.png", "Written QR", folder_id)

    pres = slides_service.presentations().get(
        presentationId=slides_id
    ).execute()

    slides = pres["slides"]
    requests = []

    # Slide 1 — exam title
    requests.append({
        "replaceAllText": {
            "containsText": {"text": "[Subject]", "matchCase": False},
            "replaceText": f"{class_name}",
        }
    })

    # Slide 3 — exam number
    requests.append({
        "replaceAllText": {
            "containsText": {"text": "[#]", "matchCase": False},
            "replaceText": exam_number,
        }
    })

    requests.append({
        "replaceAllText": {
            "containsText": {"text": "[Date]", "matchCase": False},
            "replaceText": date,
        }
    })

    # Slide 5 QR — Written solutions
    requests.append(replace_qr(slides[4], written_qr_url))

    slides_service.presentations().batchUpdate(
        presentationId=slides_id,
        body={"requests": [r for r in requests if r]},
    ).execute()


def replace_qr(slide, image_url):
    for element in slide["pageElements"]:
        if "image" in element:
            return {
                "replaceImage": {
                    "imageObjectId": element["objectId"],
                    "url": image_url,
                }
            }
    return None


def upload_image(drive, path, name, parent_id):
    media = MediaFileUpload(path, mimetype="image/png")
    file = drive.files().create(
        body={"name": name, "parents": [parent_id]},
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()

    drive.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"},
        supportsAllDrives=True
    ).execute()

    return f"https://drive.google.com/uc?id={file['id']}"


async def setup(bot):
    await bot.add_cog(WorkshopCog(bot))
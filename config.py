import os

PROJECT_ID = "bigtribebuilders"
DATASET    = "grant_helpdesk"

# Preview mode — set HELPDESK_PREVIEW=1 to run the app against a throwaway copy
# of the two tables the app WRITES to and derives status from. Everything else
# (comments, coaches, spaces, replies) still reads the real dataset, so the app
# looks and behaves exactly like production while it cannot touch it.
# Used to demo a schema change locally while coaches are working in the live app.
PREVIEW        = os.getenv("HELPDESK_PREVIEW") == "1"
_LIVE_DATASET  = f"{PROJECT_ID}.{DATASET}"
_WORK_DATASET  = f"{PROJECT_ID}.{DATASET}_preview" if PREVIEW else _LIVE_DATASET

TICKETS_TABLE  = f"{_WORK_DATASET}.grant_tickets"
META_TABLE     = f"{_WORK_DATASET}.ticket_metadata"
COMMENTS_TABLE = f"{PROJECT_ID}.{DATASET}.ticket_comments"
COMMENTS_VIEW  = f"{PROJECT_ID}.{DATASET}.grant_comments"
TEAM_TABLE     = f"{PROJECT_ID}.{DATASET}.stg_grant_team"

APP_NAME     = "Lesko Help Desk"
APP_VERSION  = "0.1"
DAILY_GOAL   = 50

# Lanes — which inbox a piece of content belongs in. This is orthogonal to
# status: a general-lane conversation still opens, gets answered and closes.
# "not a question" used to be a STATUS, which meant closing such an item erased
# the fact that it was never a question. It is a lane now.
LANE_QUESTION = "question"   # Tickets tab
LANE_GENERAL  = "general"    # Conversations tab
LANES         = [LANE_QUESTION, LANE_GENERAL]

# A ticket's lifecycle is binary: open (live) vs terminal (resolved).
# "assigned" is NOT a status — assignment is orthogonal metadata in assigned_to.
# "archived" is general-lane only: content from before the two-lane go-live,
# kept reachable via the Status filter but out of the Conversations inbox.
TICKET_STATUSES    = ["open", "answered", "closed", "cancelled", "flagged", "archived"]

# Terminal = the ticket has reached a resolved/closed end-state. Everything else
# (open, answered, flagged, NULL) is "open"/live. Single source of truth shared by
# the Open KPI and the default ticket list so the two can never diverge.
TERMINAL_STATUSES  = ["closed", "cancelled", "archived"]


def is_open_status(status) -> bool:
    """True when a ticket is live (not terminal). NULL/empty defaults to open."""
    return (status or "open") not in TERMINAL_STATUSES

MEMBER_ASSIGNMENTS_TABLE = f"{PROJECT_ID}.{DATASET}.member_assignment_overrides"
LOGS_TABLE               = f"{PROJECT_ID}.{DATASET}.app_logs"

# Dataform repository — used to trigger table refreshes after assignments change.
# DATAFORM_REGION: the GCP region your Dataform repo lives in (e.g. "europe-west4").
# DATAFORM_REPOSITORY: the repository name as it appears in the Dataform UI.
DATAFORM_REGION     = "europe-west1"
DATAFORM_REPOSITORY = "grant-helpdesk"

PROMPT_CONFIG_TABLE     = f"{PROJECT_ID}.{DATASET}.grant_prompt_config"
FEEDBACK_VIEW           = f"{PROJECT_ID}.{DATASET}.grant_classification_feedback"
CLASSIFIER_TABLE        = f"{PROJECT_ID}.{DATASET}.grant_question_classifier"

TEAM_API_KEYS_TABLE     = f"{PROJECT_ID}.{DATASET}.team_api_keys"
GRANT_COACHES_TABLE     = f"{PROJECT_ID}.{DATASET}.grant_coaches"
FOLLOWUP_QUEUE_TABLE    = f"{PROJECT_ID}.{DATASET}.followup_queue"
STANDARD_REPLIES_TABLE  = f"{PROJECT_ID}.{DATASET}.standard_replies"

# space_id → space_name lookup. Populated monthly by jobs/sync_spaces.py from
# the MN Admin API (/spaces). Read once (cached) to label which space/channel a
# ticket was commented in. Comments on a member's own profile carry space_id =
# MN_NETWORK_ID → rendered as "Member bio" (see mn_format.space_label).
SPACE_NAMES_TABLE       = f"{PROJECT_ID}.{DATASET}.space_names"

MN_NETWORK_ID  = "4022250"
MN_API_BASE    = "https://api.mn.co/admin/v1"

# The questions zone's own project/dataset (EU, owned by that zone — not this
# app's DATASET above). coach_inbox.load_member_questions reads private_threads
# and private_messages from here; nothing in this app ever writes here except
# an INSERT into private_messages (the later reply slice).
# Overridable via PRIVATE_CHAT_DATASET so the live service can be pointed at a
# non-existent dataset on purpose, to fire-drill the coach-inbox BTB_ALERT
# SOURCE_FAILED path without touching any code.
PRIVATE_CHAT_DATASET = os.getenv("PRIVATE_CHAT_DATASET", "lesko-486515.private_chat")

# Colleagues a coach can @mention from the answer pop-up. The display name is
# what MN renders in the mention (MN does not look it up by id), so keep it the
# person's real name. member_id is their Mighty Networks member id.
TAG_COLLEAGUES = [
    {"name": "Roger White",       "member_id": 20608038},
    {"name": "Amber Hawkins",     "member_id": 10443685},
    {"name": "Megan P",           "member_id": 11554451},
    {"name": "Tony Woodworth",    "member_id": 22079425},
    {"name": "Misty Fowlds",      "member_id": 13511276},
    {"name": "Rose Scarlet",      "member_id": 6460542},
]

DOMAINS = [
    "Pay Debt & Bills",
    "Home & Housing Help",
    "Cars & Car Repairs",
    "Healthcare Assistance",
    "Start A Business",
    "Launch A Nonprofit",
    "Boost Your Career",
    "Taxes Help Guidance",
    "Find Legal Help",
    "Family & Children",
    "Seniors & Disabilities",
    "Programs for Veterans",
    "Community Support",
    "Other",
]


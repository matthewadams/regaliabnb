#!/usr/bin/env python3
"""Minimal Buffer GraphQL client for Regalia's scheduled tasks (cloud runs).

Replaces the buffer-regalia MCP tool on Matthew's Mac. Talks directly to
https://api.buffer.com with a bearer token read from the BUFFER_ACCESS_TOKEN
environment variable. NEVER commit or print the token (this repo is public).

Usage (every command prints one JSON object to stdout):
  buffer_post.py channels [--org ORG_ID]
  buffer_post.py create --channel ID --text-file caption.txt --image URL [--mode shareNow] [--draft]
  buffer_post.py get --post ID
  buffer_post.py delete --post ID

`create` looks up the channel's service and adds the metadata Buffer requires:
  instagram -> {"instagram": {"type": "post", "shouldShareToFeed": true}}
  facebook  -> {"facebook": {"type": "post"}}
  tiktok    -> none
Exit status is non-zero on any API or GraphQL error, with {"ok": false, "error": ...}.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.buffer.com"
DEFAULT_ORG = "6a47fe7f7add101768cbaecc"

POST_FIELDS = """
  id text status channelId channelService dueAt sentAt externalLink
  error { message supportUrl }
"""


class BufferError(Exception):
    pass


def gql(query, variables=None, retries=3):
    token = os.environ.get("BUFFER_ACCESS_TOKEN", "").strip()
    if not token:
        raise BufferError("BUFFER_ACCESS_TOKEN is not set")
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            API_URL,
            data=body,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < retries - 1:
                time.sleep(10 * (attempt + 1))
                continue
            detail = e.read().decode(errors="replace")[:500]
            raise BufferError(f"HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(5)
                continue
            raise BufferError(f"network error: {e.reason}")
        if data.get("errors"):
            raise BufferError("; ".join(err.get("message", "?") for err in data["errors"]))
        return data["data"]
    raise BufferError("retries exhausted")


def channels(org):
    return gql(
        """query($i: ChannelsInput!) { channels(input: $i) {
             id service name displayName isDisconnected isLocked isQueuePaused } }""",
        {"i": {"organizationId": org}},
    )["channels"]


def channel_service(channel_id):
    ch = gql("query($i: ChannelInput!) { channel(input: $i) { id service isDisconnected } }",
             {"i": {"id": channel_id}})["channel"]
    if not ch:
        raise BufferError("Channel not found")
    if ch.get("isDisconnected"):
        raise BufferError(f"Channel {channel_id} ({ch['service']}) is disconnected in Buffer")
    return ch["service"]


def create(channel_id, text, image_urls, mode, draft):
    service = channel_service(channel_id)
    inp = {
        "channelId": channel_id,
        "text": text,
        "mode": mode,
        "schedulingType": "automatic",
        "needsApproval": False,
        "assets": [{"image": {"url": u}} for u in image_urls],
    }
    if draft:
        inp["saveToDraft"] = True
    if service == "instagram":
        inp["metadata"] = {"instagram": {"type": "post", "shouldShareToFeed": True}}
    elif service == "facebook":
        inp["metadata"] = {"facebook": {"type": "post"}}
    res = gql(
        """mutation($i: CreatePostInput!) { createPost(input: $i) {
             ... on PostActionSuccess { post { %s } }
             ... on MutationError { message } } }""" % POST_FIELDS,
        {"i": inp},
    )["createPost"]
    if "post" not in res or not res["post"]:
        raise BufferError(res.get("message") or "createPost returned no post")
    return res["post"]


def get(post_id):
    return gql("query($i: PostInput!) { post(input: $i) { %s } }" % POST_FIELDS,
               {"i": {"id": post_id}})["post"]


def delete(post_id):
    return gql(
        """mutation($i: DeletePostInput!) { deletePost(input: $i) {
             __typename ... on MutationError { message } } }""",
        {"i": {"id": post_id}},
    )["deletePost"]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("channels"); c.add_argument("--org", default=DEFAULT_ORG)
    cr = sub.add_parser("create")
    cr.add_argument("--channel", required=True)
    cr.add_argument("--text-file", required=True, help="UTF-8 file holding the caption")
    cr.add_argument("--image", action="append", default=[])
    cr.add_argument("--mode", default="shareNow",
                    choices=["shareNow", "addToQueue", "shareNext", "customScheduled"])
    cr.add_argument("--draft", action="store_true", help="save as a Buffer draft (never publishes)")
    g = sub.add_parser("get"); g.add_argument("--post", required=True)
    d = sub.add_parser("delete"); d.add_argument("--post", required=True)
    a = ap.parse_args()
    try:
        if a.cmd == "channels":
            out = {"ok": True, "channels": channels(a.org)}
        elif a.cmd == "create":
            with open(a.text_file, encoding="utf-8") as f:
                text = f.read().strip()
            out = {"ok": True, "post": create(a.channel, text, a.image, a.mode, a.draft)}
        elif a.cmd == "get":
            out = {"ok": True, "post": get(a.post)}
        else:
            out = {"ok": True, "result": delete(a.post)}
    except BufferError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

"""Split complete Radar prompts, retaining source IDs across every split."""

import json

import requests

from radar_model import InputTooLarge, estimate_tokens


def read_array(raw):
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Radar response must be a JSON array")
    return data


def split_records(records):
    if len(records) > 1:
        middle = len(records) // 2
        return records[:middle], records[middle:]
    # Oversized individual evidence is split without changing its original ID.
    record = records[0]
    text = record.get("text", "")
    if len(text) < 512:
        return None
    middle = len(text) // 2
    return ([{**record, "text": text[:middle]}], [{**record, "text": text[middle:]}])


def pack_records(records, prompt_for, budget):
    """Greedily pack by the whole prompt, including instructions and history."""
    batch = []
    for record in records:
        if batch and estimate_tokens(prompt_for(batch + [record])) > budget:
            yield batch
            batch = []
        batch.append(record)
    if batch:
        yield batch


def map_records(records, prompt_for, parse, client):
    """Return validated results and the number of successful leaf requests.

    A failed leaf aborts the entire operation; callers never publish partial work.
    """
    def process(batch, depth=0):
        try:
            prompt = prompt_for(batch)
            for attempt in range(2):
                if estimate_tokens(prompt) > client.input_budget:
                    raise InputTooLarge("Radar prompt exceeds input budget")
                raw = client(prompt)
                try:
                    return parse(read_array(raw), batch), 1
                except ValueError:
                    if attempt:
                        raise
                    # A model can produce valid JSON with invalid source IDs.
                    # Retry once under the same pacing and size limits; never
                    # discard invalid rows and publish the rest as complete.
                    print("  Radar 응답 검증 실패: 형식과 근거 번호 재검증 요청", flush=True)
                    prompt += ("\nYour previous answer failed validation. Follow the JSON schema "
                               "and item limit exactly. Use only IDs present in this input, "
                               "with no reused candidate IDs across groups. Return JSON only.")
        except (InputTooLarge, requests.HTTPError) as exc:
            if isinstance(exc, requests.HTTPError) and (
                exc.response is None or exc.response.status_code != 413
            ):
                raise
            halves = split_records(batch) if depth < 12 else None
            if halves is None:
                raise
            print(f"  Radar 입력 추가 분할: {len(batch)}개 항목", flush=True)
            left, left_calls = process(halves[0], depth + 1)
            right, right_calls = process(halves[1], depth + 1)
            return left + right, left_calls + right_calls

    output = []
    leaves = 0
    for batch in pack_records(records, prompt_for, client.input_budget):
        rows, calls = process(batch)
        output.extend(rows)
        leaves += calls
    return output, leaves

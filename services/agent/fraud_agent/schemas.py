AGENT_JSON_SCHEMA = {
  "type": "object",
  "required": ["decision_recommendation","rationale","key_signals","actions"],
  "properties": {
    "decision_recommendation": {"type":"string","enum":["allow","step_up","block"]},
    "rationale": {"type":"string"},
    "key_signals": {"type":"array","items":{"type":"object","required":["name","value"],
                  "properties":{"name":{"type":"string"},"value":{"type":["number","integer"]}}}},
    "actions": {"type":"array","items":{"type":"string"}}
  }
}

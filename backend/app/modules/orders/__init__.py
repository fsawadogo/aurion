"""Orders extraction + lifecycle.

LLM picks structured imaging / lab / referral / prescription orders
out of an approved note's Plan-side sections. Each extracted order is
persisted as draft; the physician confirms before any outbound
delivery (which is the EMR write-back work in #57).

Strict descriptive-mode: the extractor never introduces an order the
note doesn't already record. The prompt explicitly forbids inferring
recommendations the physician didn't dictate.
"""

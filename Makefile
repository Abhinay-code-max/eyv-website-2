.PHONY: eval eval-live

# Golden eval set for AI trip generation - replay mode (default), no real
# Gemini calls. See backend/eval/run_eval.py's docstring for what this does
# and doesn't prove, and for --cases usage.
eval:
	cd backend && python eval/run_eval.py

# Same eval set against the real Gemini API - costs real quota (20 req/day
# free tier). Prefer `make eval CASES=id1,id2` via run_eval.py --cases
# directly for a targeted live subset rather than the full set.
eval-live:
	cd backend && python eval/run_eval.py --live

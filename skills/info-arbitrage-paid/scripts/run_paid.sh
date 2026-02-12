#!/usr/bin/env bash
set -euo pipefail
cd ~/HenryBot/BettaFish
python run_pipeline.py --step paid "$@"

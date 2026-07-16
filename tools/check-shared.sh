#!/usr/bin/env bash
# Fail if a file that is meant to be shared has drifted between the three copies.
#
# This repo keeps three self-contained app dirs: the root, 1080x1920-linux (what
# the SynapseOS `chibi` package ships) and 1080x1920-windows. Some files are
# genuinely platform-specific and SHOULD differ — sprite_renderer.py and
# hud_overlay.py are the obvious ones. Others are the same module copied three
# times, and those silently rot.
#
# That is not hypothetical. The synapd backend was added to the root
# llm_client.py and config.py was updated in all three copies to advertise it —
# but 1080x1920-linux/llm_client.py never got the code. Since that variant is
# the one the ISO packages, SynapseOS shipped a chibi whose own config offered a
# "synapd" backend that its llm_client could not honour, and which silently fell
# through to llama.cpp instead of saying so.
#
# Add a file here only if all three copies are meant to be identical.
# Run from the repo root:  tools/check-shared.sh

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

SHARED=(
    config.py
    data_feeds.py
    llm_client.py
    main.py
    secfeed.py
    thoth_rag.py
    voice_input.py
    voice_output.py
)

VARIANTS=(1080x1920-linux 1080x1920-windows)

rc=0
for f in "${SHARED[@]}"; do
    if [[ ! -f $f ]]; then
        echo "MISSING  $f (listed as shared but not at the root)"
        rc=1
        continue
    fi
    root=$(md5sum "$f" | cut -d' ' -f1)
    for v in "${VARIANTS[@]}"; do
        if [[ ! -f $v/$f ]]; then
            echo "MISSING  $v/$f (listed as shared)"
            rc=1
            continue
        fi
        if [[ $(md5sum "$v/$f" | cut -d' ' -f1) != "$root" ]]; then
            echo "DRIFTED  $v/$f differs from ./$f"
            rc=1
        fi
    done
done

if [[ $rc -eq 0 ]]; then
    echo "ok — all ${#SHARED[@]} shared files are identical across all 3 copies"
else
    echo
    echo "Fix by copying the intended version over the others, e.g.:"
    echo "    cp ./llm_client.py 1080x1920-linux/llm_client.py"
fi
exit $rc

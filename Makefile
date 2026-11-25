# Every target wraps `uv run python -m pipeline <command>`; make is optional.
# The usual way in is the studio: `make studio`. `make flow` shows where the film is.
#
#   make film                  story.md -> outputs/final/heritage_short_9x16.mp4 + _16x9.mp4
#   make radio                 narration + placeholder music on black (first audience test)
#   make rough                 slow pans over keyframes + score (second test, before clips)
#   make keyframes ONLY=S03    regenerate one shot's still (cache skips the rest)
#   make shots FORCE=1         ignore the cache for the selected shots
#   make status | costs | smoke | test

PY    ?= uv run python -m pipeline
ONLY  ?=
FORCE ?=
SEL    = $(if $(ONLY),--only $(ONLY)) $(if $(FORCE),--force)

.PHONY: flow sketch references cut film radio rough script keyframes narration music shots assemble validate status smoke costs prune test setup site studio

flow:      ; $(PY) flow
sketch:    ; $(PY) sketch
references: ; $(PY) references
cut:       ; $(PY) cut
film:      ; $(PY) film $(SEL)
radio:     ; $(PY) radio $(SEL)
rough:     ; $(PY) rough $(SEL)
script:    ; $(PY) script $(if $(FORCE),--force)
keyframes: ; $(PY) keyframes $(SEL)
narration: ; $(PY) narration $(SEL)
shots:     ; $(PY) shots $(SEL)
music:     ; $(PY) music $(if $(FORCE),--force)
assemble:  ; $(PY) assemble --mode $(or $(MODE),final)
validate:  ; $(PY) validate
status:    ; $(PY) status
costs:     ; $(PY) costs
site:      ; $(PY) site
studio:    ; $(PY) studio
prune:     ; $(PY) prune
smoke:     ; $(PY) smoke $(if $(GPU),--kaggle-gpu)
test:      ; uv run pytest -q
setup:     ; uv sync

PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin

.PHONY: install uninstall test help

install:
	install -d $(BINDIR)
	install -m 755 bin/puente $(BINDIR)/puente
	@echo "Installed $(BINDIR)/puente"

uninstall:
	rm -f $(BINDIR)/puente

test:
	bash tests/smoke.sh

help:
	@echo "make install | uninstall | test"

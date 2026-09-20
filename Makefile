PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin

.PHONY: install uninstall install-escucha uninstall-escucha test test-basico test-escucha help

install:
	install -d $(BINDIR)
	install -m 755 bin/puente $(BINDIR)/puente
	@echo "Installed $(BINDIR)/puente"

uninstall:
	rm -f $(BINDIR)/puente

install-escucha:
	python3 -c 'import sys; assert sys.version_info >= (3, 11), "Se requiere Python 3.11+"'
	install -d $(BINDIR) $(PREFIX)/share/agente-puente/escucha/puente_escucha
	install -m 755 bin/puente-escucha $(BINDIR)/puente-escucha
	install -m 644 integraciones/escucha/puente_escucha/*.py $(PREFIX)/share/agente-puente/escucha/puente_escucha/

uninstall-escucha:
	rm -f $(BINDIR)/puente-escucha
	rm -f $(PREFIX)/share/agente-puente/escucha/puente_escucha/*.py

# La instalación básica sigue sin requerir Python; CI verifica ambos componentes.
test: test-basico test-escucha

test-basico:
	bash tests/smoke.sh

test-escucha:
	python3 -m unittest discover -s tests/escucha -v

help:
	@echo "make install | install-escucha | uninstall | uninstall-escucha | test"

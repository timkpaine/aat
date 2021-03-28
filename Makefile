PYTHON=python
CONFIG=./config/synthetic.cfg


run:    ## Clean and make target, run target
	$(PYTHON) -m aat --config $(CONFIG)

runcpp:  build  ## Clean and make target, run target
	AAT_USE_CPP=1 $(PYTHON) -m aat  --config $(CONFIG)

rundebug:  debug  ## Clean and make debug target, run target
	$(PYTHON) -m aat  --config $(CONFIG)

stratres:  ## View strategy results offline
	$(PYTHON) -m aat.strategy.calculations

buildextf: ## build the package extensions
	$(PYTHON) setup.py build_ext -j8 --inplace -f

buildext: ## build the package extensions
	$(PYTHON) setup.py build_ext -j8 --inplace

build: buildext  ## build the package
	$(PYTHON) setup.py build

debug: ## build debug build of the package
	DEBUG=1 $(PYTHON) setup.py build

js:  ## build the js assets
	cd js; yarn build

install: ## install the package
	$(PYTHON) -m pip install .

tests: build testpy  ## Make unit tests

testpy: ## Make unit tests
	$(PYTHON) -m pytest -vvv ./aat/tests --cov=aat --junitxml=python_junit.xml --cov-report=xml --cov-branch

testpycpp: ## Make unit tests
	# AAT_USE_CPP=1 $(PYTHON) -m pytest -vvv ./aat/tests --cov=aat --junitxml=python_junit.xml --cov-report=xml --cov-branch --capture=no
	AAT_USE_CPP=1 $(PYTHON) -m pytest -vs ./aat/tests

testjs:  ## Make js tests
	cd js; yarn test

testruns:  testrunscsv testrunsiex testrunsother ## Run a few examples as a live end-to-end test

testrunsother:
	$(PYTHON) -m aat.exchange.test.harness
	$(PYTHON) -m aat.tests.exchange.test_ib_race

testrunscsv:
	$(PYTHON) -m aat.strategy.sample.csv.readonly
	$(PYTHON) -m aat.strategy.sample.csv.readonly_periodic
	$(PYTHON) -m aat.strategy.sample.csv.received

testrunsiex:
	$(PYTHON) -m aat.strategy.sample.iex.readonly
	TESTING=1 $(PYTHON) -m aat.strategy.sample.iex.buy_and_hold
	TESTING=1 $(PYTHON) -m aat.strategy.sample.iex.momentum
	TESTING=1 $(PYTHON) -m aat.strategy.sample.iex.golden_death

lint: lintpy lintjs lintcpp  ## run all linters

lintpy: ## run python linter
	$(PYTHON) -m flake8 aat setup.py

lintjs: ## run js linter
	cd js; yarn lint
	
lintcpp: ## run cpp linter
	cpplint --linelength=120 --recursive aat/cpp/{src,include}

fix: fixpy fixjs fixcpp  ## run all fixers

fixpy:  ## run autopep8 fix
	$(PYTHON) -m black aat/ setup.py

fixcpp:  ## run clang-format
	clang-format -i -style=file `find ./aat/cpp/{src,include} -name "*.*pp"`

fixjs:  ## run clang-format
	cd js; yarn fix

annotate: ## MyPy type annotation check
	$(PYTHON) -m mypy aat

type_ignore:  ## Count type ignores
    grep -rin "type: ignore" ./aat | wc -l

type_ignore_list:  ## List all type ignores
    grep -rin "type: ignore" ./aat

docs:  ## Build the sphinx docs
	make -C docs html
	open ./docs/_build/html/index.html

dist: js  ## create dists
	rm -rf dist build
	python setup.py sdist bdist_wheel
	python -m twine check dist/*

publish: dist  ## dist to pypi and npm
	python -m twine upload dist/* --skip-existing
	cd js; npm publish || echo "can't publish - might already exist"

clean: ## clean the repository
	find . -name "__pycache__" | xargs rm -rf
	find . -name "*.pyc" | xargs rm -rf
	rm -rf .coverage coverage cover htmlcov logs build dist *.egg-info coverage.xml .mypy_cache
	find . -name "*.so"  | xargs rm -rf
	make -C ./docs clean
	rm -rf _aat_BACKTEST_*

# Thanks to Francoise at marmelab.com for this
.DEFAULT_GOAL := help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

print-%:
	@echo '$*=$($*)'

.PHONY: run buildext build js install tests lint fix docs dist clean help fixcpp


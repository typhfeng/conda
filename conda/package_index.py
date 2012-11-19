''' The package_index module provides the package_index class, which is the primary interface for looking up packages and their
dependencies, matching packages to constraints, etc.

'''


from constraints import satisfies
from package import package
from package_spec import find_inconsistent_specs


class package_index(object):
    ''' Encapsulates an Anaconda package index

    Parameters
    ----------
    info : dict
        dictionary of (package filename : package info) pairs

    Attributes
    ----------
    deps
    package_names
    rdeps

    '''

    def __init__(self, info):

        self.pkg_filenames = dict(
            (pkg_filename, package(pkg_info))
            for pkg_filename, pkg_info in info.items()
        )

        self.pkgs = set(
            package(pkg_info) for pkg_info in info.values()
        )

        # compute on demand
        self._deps = None
        self._rdeps = None

    @property
    def deps(self):
        ''' Return the entire dependency graph '''
        if not self._deps:
            self._deps = self._compute_dependencies()
        return self._deps

    @property
    def rdeps(self):
        ''' Return the entire reverse dependency graph '''
        if not self._rdeps:
            self._rdeps = self._compute_reverse_dependencies()
        return self._rdeps

    @property
    def package_names(self):
        ''' Return a set of all package names for packages in this index '''
        return set([pkg.name for pkg in self.pkgs])

    def lookup_from_filename(self, pkg_filename):
        ''' Return a :py:class`package <conda.package.package>` object corresponding to the given package filename

        Parameters
        ----------
        pkg_filename : str
            package filename of package to look up

        Returns
        -------
        package : :py:class`package <conda.package.package>` object
            matching package, if one is found

        '''
        return self.pkg_filenames[pkg_filename]

    def lookup_from_canonical_name(self, canonical_name):
        ''' Return a :py:class`package <conda.package.package>` object corresponding to the given canonical name

        Parameters
        ----------
        canonical_name : str
            canonical_name of package to look up

        Returns
        -------
        package : :py:class`package <conda.package.package>` object
            matching package, if one is found

        '''
        return self.pkg_filenames[canonical_name+'.tar.bz2']

    def lookup_from_name(self, pkg_name):
        ''' Return a set of :py:class`package <conda.package.package>` objects with the given package name

        Parameters
        ----------
        name : str
            name of packages to look up

        Returns
        -------
        package : set of :py:class`package <conda.package.package>` objects
            matching packages

        '''
        return set([pkg for pkg in self.pkgs if pkg.name == pkg_name])

    def find_matches(self, constraint, pkgs=None):
        ''' Return a set of :py:class`package <conda.package.package>` objects that match the given constraint

        Parameters
        ----------
        constraint : :py:class:`constraint <conda.constraints.package_constraint>` object
            constraint to match
        pkgs : iterable of :py:class`package <conda.package.package>` objects, optional
            if supplied, search only packages in this collection

        Returns
        -------
        matches : set of iterable of :py:class`package <conda.package.package>` objects
            matching packages

        '''
        if not pkgs is not None: pkgs = self.pkgs
        return set([pkg for pkg in pkgs if pkg.matches(constraint)])

    def get_deps(self, pkgs, max_depth=0):
        ''' Return mutual package dependencies for a collection of packages

        Parameters
        ----------
        pkgs : iterable of :py:class:`constraint <conda.package.package>` objects
            packages to find dependencies for
        max_depth : bool, optional
            how many levels of the dependency graph to search, defaults to 0 (all levels)

        Returns
        -------
        deps : set of :py:class:`requirement <conda.requirement.requirement>` objects
            mutual dependencies of all the supplied packages

        '''
        deps = set()
        pkgs = set(pkgs)
        iterations = 0
        last_deps = None

        while True:
            if max_depth and iterations >= max_depth: break
            for pkg in pkgs:
                deps |= self.deps.get(pkg, set())
            if deps == last_deps: break
            pkgs = deps - pkgs
            last_deps = deps
            iterations += 1

        return deps

    def get_reverse_deps(self, pkgs, max_depth=0):
        ''' Return mutual reverse dependencies for a collection of requirements

        Parameters
        ----------
        pkgs : iterable of  :py:class:`requirement <conda.package.package>` objects
            package to find reverse dependencies for
        max_depth : bool, optional
            how many levels of the reverse dependency graph to search, defaults to 0 (all levels)

        Returns
        -------
        rdeps : set of :py:class:`constraint <conda.package.package>` objects
            mutual reverse dependencies of all the supplied requirements

        '''
        rdeps = set()
        pkgs = set(pkgs)
        iterations = 0
        last_rdeps = None

        while True:
            if max_depth and iterations >= max_depth: break
            for pkg in pkgs:
                rdeps |= self.rdeps.get(pkg, set())
            if rdeps == last_rdeps: break
            pkgs = rdeps - pkgs
            last_rdeps = rdeps
            iterations += 1

        return rdeps

    def find_compatible_requirements(self, pkgs):
        '''
        For a set of packages, return the complete set of requirements that all
        of the packages packages satisfy together.

        Parameters
        ----------
        pkgs : iterable of :py:class:`constraint <conda.constraints.package_constraint>` objects
            collection of packages to compile requirements for

        Returns
        -------
        reqs : set of :py:class:`requirement <conda.requirement.requirement>` objects
            requirements satisfied by all the given packages

        '''
        reqs = set()
        for pkg in pkgs:
            for req in self.rdeps:
                if pkg.matches(satisfies(req)):
                    reqs.add(req)
        return reqs

    def find_compatible_packages(self, reqs):
        '''
        For a set of requirements, return the complete set of packages that
        satisfies all the requirements jointly.

        Parameters
        ----------
        reqs : iterable of py:class:`requirement <conda.requirement.requirement>` objects
            collection of requirements to find packages for

        Returns
        -------
        pkgs : set of :py:class:`constraint <conda.constraints.package_constraint>` objects:
            packages that satisfy by all the given requirements

        '''
        pkgs = set()

        # find all the packages that satisfy any of the requirements (these may
        # include packages inconsistent with other requirements)
        for req in reqs:
            if req.build:
                pkg_filename = "%s-%s-%s.tar.bz2" % (req.name,
                                                     req.version.vstring,
                                                     req.build)
                pkgs.add(self.lookup_from_filename(pkg_filename))
            else:
                pkgs = pkgs | self.find_matches(satisfies(req))

        # remove any packages whose requirements are inconsistent with the
        # user specified requirements
        to_remove = set()
        for pkg in pkgs:
            inconsistent = find_inconsistent_specs(reqs | pkg.requires)
            if inconsistent: to_remove.add(pkg)
        pkgs = pkgs - to_remove

        return pkgs

    def _compute_dependencies(self):
        deps = dict()
        for pkg in self.pkgs:
            if pkg.is_meta: continue
            deps[pkg] = set()
            for req in pkg.requires:
                deps[pkg] |= self.find_matches(satisfies(req))
        return deps

    def _compute_reverse_dependencies(self):
        rdeps = dict()
        for pkg, deps in self.deps.items():
            for dep in deps:
                if dep not in rdeps:
                    rdeps[dep] = set()
                rdeps[dep].add(pkg)
        return rdeps


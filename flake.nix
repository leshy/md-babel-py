{
  description = "md-babel-py - Execute code blocks in markdown files";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        # Python package
        md-babel-py = pkgs.python312Packages.buildPythonApplication {
          pname = "md-babel-py";
          version = "0.1.0";
          src = ./.;
          format = "pyproject";

          nativeBuildInputs = [ pkgs.python312Packages.setuptools ];

          # Optional matplotlib support
          propagatedBuildInputs = with pkgs.python312Packages; [
            matplotlib
            numpy
          ];

          meta = {
            description = "Execute code blocks in markdown files with session support";
            license = pkgs.lib.licenses.mit;
          };
        };

        # Python with matplotlib for code blocks
        pythonWithPackages = pkgs.python312.withPackages (ps: [
          ps.matplotlib
          ps.numpy
        ]);

        # All evaluator dependencies
        evaluatorDeps = with pkgs; [
          # Core
          bash
          coreutils

          # Languages
          pythonWithPackages
          nodejs

          # Graphics tools
          graphviz
          asymptote
          pikchr
          openscad
          imagemagick

          # OpenSCAD needs a virtual framebuffer
          xvfb-run
        ];

        # Runtime wrapper that includes all evaluators in PATH
        md-babel-py-full = pkgs.symlinkJoin {
          name = "md-babel-py-full";
          paths = [ md-babel-py ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postBuild = ''
            wrapProgram $out/bin/md-babel-py \
              --prefix PATH : ${pkgs.lib.makeBinPath evaluatorDeps}
          '';
        };

      in {
        packages = {
          default = md-babel-py-full;
          minimal = md-babel-py;
        };

        apps.default = {
          type = "app";
          program = "${md-babel-py-full}/bin/md-babel-py";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            md-babel-py
            pkgs.python312Packages.pytest
            pkgs.python312Packages.mypy
            pkgs.python312Packages.ruff
          ] ++ evaluatorDeps;
        };

        # Docker image
        packages.docker = pkgs.dockerTools.buildLayeredImage {
          name = "md-babel-py";
          tag = "latest";

          contents = [
            md-babel-py-full
            pkgs.bashInteractive
            pkgs.coreutils
          ] ++ evaluatorDeps;

          # Create /usr/bin/env symlink and config directory
          extraCommands = ''
            mkdir -p usr/bin
            ln -s ${pkgs.coreutils}/bin/env usr/bin/env
            mkdir -p root/.config/md-babel
            cp ${./config.json} root/.config/md-babel/config.json
          '';

          config = {
            Entrypoint = [ "${md-babel-py-full}/bin/md-babel-py" ];
            WorkingDir = "/work";
            Env = [
              "HOME=/root"
              "FONTCONFIG_FILE=${pkgs.fontconfig.out}/etc/fonts/fonts.conf"
            ];
          };
        };
      }
    );
}

#!/bin/bash

conda init
conda init zsh
echo $ZSH_CUSTOM
git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
git clone https://github.com/zsh-users/zsh-syntax-highlighting.git ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting
sed -i "s|plugins=(git)|plugins=(git zsh-autosuggestions zsh-syntax-highlighting)|g" ~/.zshrc
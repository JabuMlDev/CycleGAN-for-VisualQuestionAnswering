import argparse
import os
import sys

import torch
import torchvision.transforms as transforms
from PIL import Image
from torch.utils.data import DataLoader
from torch.autograd import Variable
from torchvision.utils import save_image

from cycleGAN.models import Generator
from cycleGAN.datasets import ImageDataset

os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

os.environ['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
os.environ['CUDA_VISIBLE_DEVICES'] = '1'

parser = argparse.ArgumentParser()
parser.add_argument('--batchSize', type=int, default=1, help='size of the batches')
parser.add_argument('--images_path', type=str, default='', help='paths of the images that must be transformed')
parser.add_argument('--label_datasetA', type=str,default='artpedia', help='label of the dataset to transform')
parser.add_argument('--input_nc', type=int, default=3, help='number of channels of input data')
parser.add_argument('--output_nc', type=int, default=3, help='number of channels of output data')
parser.add_argument('--size', type=int, default=256, help='size of the data (squared assumed)')
parser.add_argument('--cuda', action='store_true', help='use GPU computation')
parser.add_argument('--n_cpu', type=int, default=8, help='number of cpu threads to use during batch generation')
parser.add_argument('--generator_A2B', type=str, default='cycleGAN/output/netG_artpedia2visualgenome.pth',
                    help='A2B generator checkpoint file')
opt = parser.parse_args()
print(opt)

if __name__ == '__main__':
    if torch.cuda.is_available() and not opt.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")

    ###### Definition of variables ######
    # Networks
    netG_A2B = Generator(opt.input_nc, opt.output_nc)

    if opt.cuda:
        netG_A2B.cuda()
        # Load state dicts
        netG_A2B.load_state_dict(torch.load(opt.generator_A2B))
    else:
        netG_A2B.load_state_dict(torch.load(opt.generator_A2B, map_location=torch.device('cpu')))

    Tensor = torch.cuda.FloatTensor if opt.cuda else torch.Tensor

    # Dataset loader
    transforms_ = [transforms.Resize(int(opt.size*2), Image.BICUBIC),
                   transforms.ToTensor(), transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))]

    path_output_imgs = "./cycleGAN/output/" + opt.label_datasetA + "_dt"
    # Create output dirs if they don't exist
    if not os.path.exists(path_output_imgs):
        os.makedirs(path_output_imgs)

    images_dirs = opt.images_path.split(",")
    dataloader = DataLoader(ImageDataset(images_dirs, transforms_=transforms_,
                                         label_datasetA=opt.label_datasetA, transform_mode=True,
                                         existing_path=path_output_imgs),
                            batch_size=opt.batchSize, shuffle=False, num_workers=opt.n_cpu)
    ###################################

    for i, batch in enumerate(dataloader):
        # Set model input
        input = Tensor(opt.batchSize, opt.input_nc, batch[opt.label_datasetA].shape[2],
                       batch[opt.label_datasetA].shape[3])
        real = Variable(input.copy_(batch[opt.label_datasetA]))
        img_idx = batch["name"][0]
        # Generate output
        fake = 0.5*(netG_A2B(real).data + 1.0)

        # Save image files
        save_image(fake, path_output_imgs+'/%04d.png' % (int(img_idx)))

        sys.stdout.write('\rGenerated images %04d of %04d' % (i+1, len(dataloader)))


    sys.stdout.write('\n')
###################################

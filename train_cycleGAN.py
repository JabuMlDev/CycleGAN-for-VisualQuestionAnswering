#!/usr/bin/python3

import argparse
import itertools

import torchvision.transforms as transforms
from torch.utils.data import DataLoader
from torch.autograd import Variable
from PIL import Image
import torch

from cycleGAN.models import Generator
from cycleGAN.models import Discriminator
from cycleGAN.utils import ReplayBuffer
from cycleGAN.utils import LambdaLR
from cycleGAN.utils import Logger
from cycleGAN.utils import weights_init_normal
from cycleGAN.datasets import ImageDataset
import os

os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

#os.environ['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
#os.environ['CUDA_VISIBLE_DEVICES'] = '0'

parser = argparse.ArgumentParser()
parser.add_argument('--epoch', type=int, default=0, help='starting epoch')
parser.add_argument('--n_epochs', type=int, default=200, help='number of epochs of training')
parser.add_argument('--batchSize', type=int, default=1, help='size of the batches')
parser.add_argument('--datarootA', type=str, default='', help='directories of the dataset A')
parser.add_argument('--percent_trainA', type=float, default=70, help='percent of data to use for train A'
                                                                      '(None if splitting is in dir)')
parser.add_argument('--datarootB', type=str, default='', help='directories of the dataset B')
parser.add_argument('--percent_trainB', type=float, default=None, help='percent of data to use for train B'
                                                                      '(None if splitting is in dir)')
parser.add_argument('--label_datasetA', type=str,default='visualgenome', help='label of the dataset to transform')
parser.add_argument('--label_datasetB', type=str,default='artpedia', help='label of the dataset to transformation')
parser.add_argument('--lr', type=float, default=0.00001, help='initial learning rate')
parser.add_argument('--decay_epoch', type=int, default=100, help='epoch to start linearly decaying the learning rate to 0')
parser.add_argument('--size', type=int, default=256, help='size of the data crop (squared assumed)')
parser.add_argument('--input_nc', type=int, default=3, help='number of channels of input data')
parser.add_argument('--output_nc', type=int, default=3, help='number of channels of output data')
parser.add_argument('--cuda', action='store_true', help='use GPU computation')
parser.add_argument('--n_cpu', type=int, default=16, help='number of cpu threads to use during batch generation')
parser.add_argument('--load_models', type=bool, default=False, help='set if the models must be read from files')

opt = parser.parse_args()
print(opt)

if __name__ == '__main__':

    if torch.cuda.is_available() and not opt.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")

    ###### Definition of variables ######
    # Networks
    netG_A2B = Generator(opt.input_nc, opt.output_nc)
    netG_B2A = Generator(opt.output_nc, opt.input_nc)
    netD_A = Discriminator(opt.input_nc)
    netD_B = Discriminator(opt.output_nc)

    if opt.cuda:
        netG_A2B.cuda()
        netG_B2A.cuda()
        netD_A.cuda()
        netD_B.cuda()

    if opt.load_models:
        try:
            netG_A2B.load_state_dict(torch.load( 'cycleGAN/output/netG_' + opt.label_datasetA + '2' + opt.label_datasetB + '.pth'))
            netG_B2A.load_state_dict(torch.load( 'cycleGAN/output/netG_' + opt.label_datasetB + '2' + opt.label_datasetA + '.pth'))
            netD_A.load_state_dict(torch.load(  'cycleGAN/output/netD_' + opt.label_datasetA + '.pth'))
            netD_B.load_state_dict(torch.load(  'cycleGAN/output/netD_' + opt.label_datasetB + '.pth'))
        except RuntimeError:
            if not opt.cuda:
                netG_A2B.load_state_dict(
                    torch.load('cycleGAN/output/netG_' + opt.label_datasetA + '2' + opt.label_datasetB + '.pth',
                               map_location=torch.device('cpu')))
                netG_B2A.load_state_dict(
                    torch.load('cycleGAN/output/netG_' + opt.label_datasetB + '2' + opt.label_datasetA + '.pth',
                               map_location=torch.device('cpu')))
                netD_A.load_state_dict(torch.load('cycleGAN/output/netD_' + opt.label_datasetA + '.pth',
                              map_location=torch.device('cpu')))
                netD_B.load_state_dict(torch.load('cycleGAN/output/netD_' + opt.label_datasetB + '.pth',
                              map_location=torch.device('cpu')))
            else:
                RuntimeError()

    else:
        netG_A2B.apply(weights_init_normal)
        netG_B2A.apply(weights_init_normal)
        netD_A.apply(weights_init_normal)
        netD_B.apply(weights_init_normal)

    # Lossess
    criterion_GAN = torch.nn.MSELoss()
    criterion_cycle = torch.nn.L1Loss()
    criterion_identity = torch.nn.L1Loss()

    # Optimizers & LR schedulers
    optimizer_G = torch.optim.Adam(itertools.chain(netG_A2B.parameters(), netG_B2A.parameters()),
                                    lr=opt.lr, betas=(0.5, 0.999))
    optimizer_D_A = torch.optim.Adam(netD_A.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    optimizer_D_B = torch.optim.Adam(netD_B.parameters(), lr=opt.lr, betas=(0.5, 0.999))

    lr_scheduler_G = torch.optim.lr_scheduler.LambdaLR(optimizer_G, lr_lambda=LambdaLR(opt.n_epochs, opt.epoch, opt.decay_epoch).step)
    lr_scheduler_D_A = torch.optim.lr_scheduler.LambdaLR(optimizer_D_A, lr_lambda=LambdaLR(opt.n_epochs, opt.epoch, opt.decay_epoch).step)
    lr_scheduler_D_B = torch.optim.lr_scheduler.LambdaLR(optimizer_D_B, lr_lambda=LambdaLR(opt.n_epochs, opt.epoch, opt.decay_epoch).step)

    # Inputs & targets memory allocation
    Tensor = torch.cuda.FloatTensor if opt.cuda else torch.Tensor
    input_A = Tensor(opt.batchSize, opt.input_nc, opt.size, opt.size)
    input_B = Tensor(opt.batchSize, opt.output_nc, opt.size, opt.size)
    target_real = Variable(Tensor(opt.batchSize).fill_(1.0), requires_grad=False)
    target_fake = Variable(Tensor(opt.batchSize).fill_(0.0), requires_grad=False)

    fake_A_buffer = ReplayBuffer()
    fake_B_buffer = ReplayBuffer()

    # Dataset loader
    transforms_ = [ transforms.Resize(int(int(opt.size*1.12)), Image.BICUBIC),
                    transforms.RandomCrop(opt.size),
                    transforms.RandomHorizontalFlip(),
                    transforms.ToTensor(),
                    transforms.Normalize((0.5,0.5,0.5), (0.5,0.5,0.5)) ]
    datarootA = opt.datarootA.split(",")
    datarootB = opt.datarootB.split(",")
    dataloader = DataLoader(ImageDataset(pathA=datarootA, pathB=datarootB, transforms_=transforms_, unaligned=True,
                                         label_datasetA=opt.label_datasetA, label_datasetB=opt.label_datasetB,
                                         percent_trainA=opt.percent_trainA, percent_trainB=opt.percent_trainB),
                            batch_size=opt.batchSize, shuffle=True, num_workers=opt.n_cpu)

    # Loss plot
    logger = Logger(opt.n_epochs, len(dataloader), opt.epoch)
    ###################################

    ###### Training ######
    for epoch in range(opt.epoch, opt.n_epochs):
        for i, batch in enumerate(dataloader):
            # Set model input
            real_A = Variable(input_A.copy_(batch[opt.label_datasetA]))
            real_B = Variable(input_B.copy_(batch[opt.label_datasetB]))

            ###### Generators A2B and B2A ######
            optimizer_G.zero_grad()

            # Identity loss
            # G_A2B(B) should equal B if real B is fed
            same_B = netG_A2B(real_B)
            loss_identity_B = criterion_identity(same_B, real_B)*5.0
            # G_B2A(A) should equal A if real A is fed
            same_A = netG_B2A(real_A)
            loss_identity_A = criterion_identity(same_A, real_A)*5.0

            # GAN loss
            fake_B = netG_A2B(real_A)
            pred_fake = netD_B(fake_B)
            loss_GAN_A2B = criterion_GAN(pred_fake, target_real)

            fake_A = netG_B2A(real_B)
            pred_fake = netD_A(fake_A)
            loss_GAN_B2A = criterion_GAN(pred_fake, target_real)

            # Cycle loss
            recovered_A = netG_B2A(fake_B)
            loss_cycle_ABA = criterion_cycle(recovered_A, real_A)*10.0

            recovered_B = netG_A2B(fake_A)
            loss_cycle_BAB = criterion_cycle(recovered_B, real_B)*10.0

            # Total loss
            loss_G = loss_identity_A + loss_identity_B + loss_GAN_A2B + loss_GAN_B2A + loss_cycle_ABA + loss_cycle_BAB
            loss_G.backward()

            optimizer_G.step()
            ###################################

            ###### Discriminator A ######
            optimizer_D_A.zero_grad()

            # Real loss
            pred_real = netD_A(real_A)
            loss_D_real = criterion_GAN(pred_real, target_real)

            # Fake loss
            fake_A = fake_A_buffer.push_and_pop(fake_A)
            pred_fake = netD_A(fake_A.detach())
            loss_D_fake = criterion_GAN(pred_fake, target_fake)

            # Total loss
            loss_D_A = (loss_D_real + loss_D_fake)*0.5
            loss_D_A.backward()

            optimizer_D_A.step()
            ###################################

            ###### Discriminator B ######
            optimizer_D_B.zero_grad()

            # Real loss
            pred_real = netD_B(real_B)
            loss_D_real = criterion_GAN(pred_real, target_real)

            # Fake loss
            fake_B = fake_B_buffer.push_and_pop(fake_B)
            pred_fake = netD_B(fake_B.detach())
            loss_D_fake = criterion_GAN(pred_fake, target_fake)

            # Total loss
            loss_D_B = (loss_D_real + loss_D_fake)*0.5
            loss_D_B.backward()

            optimizer_D_B.step()
            ###################################

            # Progress report (http://localhost:8097)
            logger.log({'loss_G': loss_G, 'loss_G_identity': (loss_identity_A + loss_identity_B), 'loss_G_GAN': (loss_GAN_A2B + loss_GAN_B2A),
                        'loss_G_cycle': (loss_cycle_ABA + loss_cycle_BAB), 'loss_D': (loss_D_A + loss_D_B)},
                        images={'real_'+opt.label_datasetA: real_A, 'real_'+opt.label_datasetB: real_B,
                                'fake_'+opt.label_datasetA: fake_A, 'fake_'+opt.label_datasetB: fake_B})

        # Update learning rates
        lr_scheduler_G.step()
        lr_scheduler_D_A.step()
        lr_scheduler_D_B.step()

        torch.save(netG_A2B.state_dict(),
                   'cycleGAN/output/netG_' + opt.label_datasetA + '2' + opt.label_datasetB + '.pth')
        torch.save(netG_B2A.state_dict(),
                   'cycleGAN/output/netG_' + opt.label_datasetB + '2' + opt.label_datasetA + '.pth')
        torch.save(netD_A.state_dict(), 'cycleGAN/output/netD_' + opt.label_datasetA + '.pth')
        torch.save(netD_B.state_dict(), 'cycleGAN/output/netD_' + opt.label_datasetB + '.pth')

    ###################################